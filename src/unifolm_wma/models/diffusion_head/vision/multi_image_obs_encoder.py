import copy
import torch
import torch.nn as nn
import torchvision
import json
import os

from unifolm_wma.models.diffusion_head.vision.crop_randomizer import CropRandomizer
from unifolm_wma.models.diffusion_head.base_nets import SpatialSoftmax
from unifolm_wma.models.diffusion_head.common.module_attr_mixin import ModuleAttrMixin
from unifolm_wma.models.diffusion_head.common.pytorch_util import dict_apply, replace_submodules
from unifolm_wma.utils.utils import instantiate_from_config
from einops import rearrange, repeat
from typing import Dict, Tuple, Union
from pathlib import Path


class MultiImageObsEncoder(ModuleAttrMixin):

    def __init__(
            self,
            rgb_model_config: Dict,
            shape_meta_path: str | None = None,
            resize_shape: Union[Tuple[int, int], Dict[str, tuple],
                                None] = None,
            crop_shape: Union[Tuple[int, int], Dict[str, tuple], None] = None,
            random_crop: bool = True,
            # replace BatchNorm with GroupNorm
            use_group_norm: bool = False,
            # use single rgb model for all rgb inputs
            share_rgb_model: bool = False,
            # renormalize rgb input with imagenet normalization
            # assuming input in [0,1]
            imagenet_norm: bool = False,
            use_spatial_softmax=False,
            spatial_softmax_kp=32,
            use_dinoSiglip=False):
        """
        Assumes rgb input: B,C,H,W
        Assumes low_dim input: B,D
        """
        super().__init__()

        if not shape_meta_path:
            shape_meta_path = str(Path(os.getcwd()) / "configs/train/meta.json")

        with open(shape_meta_path, 'r') as file:
            shape_meta = json.load(file)

        rgb_model = instantiate_from_config(rgb_model_config)

        rgb_keys = list()
        low_dim_keys = list()
        key_model_map = nn.ModuleDict()
        key_transform_map = nn.ModuleDict()
        key_shape_map = dict()

        # handle sharing vision backbone
        if share_rgb_model:
            assert isinstance(rgb_model, nn.Module)
            key_model_map['rgb'] = rgb_model

        obs_shape_meta = shape_meta['obs']
        for key, attr in obs_shape_meta.items():
            shape = tuple(attr['shape'])
            type = attr.get('type', 'low_dim')
            key_shape_map[key] = shape
            if type == 'rgb':
                rgb_keys.append(key)
                if not use_dinoSiglip:
                    # configure model for this key
                    this_model = None
                    if not share_rgb_model:
                        if isinstance(rgb_model, dict):
                            # have provided model for each key
                            this_model = rgb_model[key]
                        else:
                            assert isinstance(rgb_model, nn.Module)
                            # have a copy of the rgb model
                            this_model = copy.deepcopy(rgb_model)

                    if this_model is not None:
                        if use_group_norm:
                            this_model = replace_submodules(
                                root_module=this_model,
                                predicate=lambda x: isinstance(
                                    x, nn.BatchNorm2d),
                                func=lambda x: nn.GroupNorm(
                                    num_groups=x.num_features // 16,
                                    num_channels=x.num_features))
                        key_model_map[key] = this_model

                    # configure resize
                    input_shape = shape
                    this_resizer = nn.Identity()
                    if resize_shape is not None:
                        if isinstance(resize_shape, dict):
                            h, w = resize_shape[key]
                        else:
                            h, w = resize_shape
                        this_resizer = torchvision.transforms.Resize(size=(h,
                                                                           w))
                        input_shape = (shape[0], h, w)

                    # configure randomizer
                    this_randomizer = nn.Identity()
                    if crop_shape is not None:
                        if isinstance(crop_shape, dict):
                            h, w = crop_shape[key]
                        else:
                            h, w = crop_shape
                        if random_crop:
                            this_randomizer = CropRandomizer(
                                input_shape=input_shape,
                                crop_height=h,
                                crop_width=w,
                                num_crops=1,
                                pos_enc=False)
                        else:
                            this_normalizer = torchvision.transforms.CenterCrop(
                                size=(h, w))
                    # configure normalizer
                    this_normalizer = nn.Identity()
                    if imagenet_norm:
                        this_normalizer = torchvision.transforms.Normalize(
                            mean=[0.485, 0.456, 0.406],
                            std=[0.229, 0.224, 0.225])

                    this_transform = nn.Sequential(this_resizer,
                                                   this_randomizer,
                                                   this_normalizer)
                    key_transform_map[key] = this_transform
                else:
                    key_model_map[key] = rgb_model
            elif type == 'low_dim':
                low_dim_keys.append(key)
            else:
                raise RuntimeError(f"Unsupported obs type: {type}")

        rgb_keys = sorted(rgb_keys)
        low_dim_keys = sorted(low_dim_keys)

        self.shape_meta = shape_meta
        self.key_model_map = key_model_map
        self.key_transform_map = key_transform_map
        self.share_rgb_model = share_rgb_model
        self.rgb_keys = rgb_keys
        self.low_dim_keys = low_dim_keys
        self.key_shape_map = key_shape_map
        self.use_dinoSiglip = use_dinoSiglip

        ##NOTE add spatial softmax
        self.use_spatial_softmax = use_spatial_softmax
        if use_spatial_softmax and not use_dinoSiglip:
            model = nn.Sequential(
                key_model_map['image'].conv1,
                key_model_map['image'].bn1,
                key_model_map['image'].relu,
                key_model_map['image'].maxpool,
                key_model_map['image'].layer1,
                key_model_map['image'].layer2,
                key_model_map['image'].layer3,
                key_model_map['image'].layer4,
            )
            key_model_map['image'] = model
            input_shape = self.output_shape(resnet_output_shape=True)
            self.spatial_softmax = SpatialSoftmax(input_shape,
                                                  num_kp=spatial_softmax_kp)

    def forward(self, obs_dict, resnet_output_shape=False):
        batch_size = None
        features = list()
        # process rgb input
        if self.share_rgb_model:
            # pass all rgb obs to rgb model
            imgs = list()
            for key in self.rgb_keys:
                img = obs_dict[key]
                if batch_size is None:
                    batch_size = img.shape[0]
                else:
                    assert batch_size == img.shape[0]
                assert img.shape[1:] == self.key_shape_map[key]
                img = self.key_transform_map[key](img)
                imgs.append(img)
            # (N*B,C,H,W)
            imgs = torch.cat(imgs, dim=0)
            # (N*B,D)
            feature = self.key_model_map['rgb'](imgs)
            # (N,B,D)
            feature = feature.reshape(-1, batch_size, *feature.shape[1:])
            # (B,N,D)
            feature = torch.moveaxis(feature, 0, 1)
            # (B,N*D)
            feature = feature.reshape(batch_size, -1)
            features.append(feature)
        else:
            # run each rgb obs to independent models
            for key in self.rgb_keys:
                img = obs_dict[key]
                if batch_size is None:
                    batch_size = img.shape[0]
                else:
                    assert batch_size == img.shape[0]
                # 打印调试信息
                print(f"[DEBUG] key: {key}")
                print(f"[DEBUG] img.shape: {img.shape}")
                print(f"[DEBUG] expected shape: {self.key_shape_map[key]}")
                assert img.shape[1:] == self.key_shape_map[key]
                if not self.use_dinoSiglip:
                    img = self.key_transform_map[key](img)
                    feature = self.key_model_map[key](img)
                else:
                    feature = self.key_model_map[key](img)[:, :1, :]

                if resnet_output_shape:
                    return feature
                if not self.use_dinoSiglip and self.use_spatial_softmax:
                    feature = self.spatial_softmax(feature)
                feature = feature.reshape(batch_size, -1)
                features.append(feature)

        # process lowdim input
        for key in self.low_dim_keys:
            data = obs_dict[key]
            if batch_size is None:
                batch_size = data.shape[0]
            else:
                assert batch_size == data.shape[0]
            assert data.shape[1:] == self.key_shape_map[key]
            features.append(data)

        # concatenate all features
        result = torch.cat(features, dim=-1)
        return result

    @torch.no_grad()
    def output_shape(self, resnet_output_shape=False):
        example_obs_dict = dict()
        obs_shape_meta = self.shape_meta['obs']
        batch_size = 1
        for key, attr in obs_shape_meta.items():
            shape = tuple(attr['shape'])
            this_obs = torch.zeros((batch_size, ) + shape,
                                   dtype=self.dtype,
                                   device=self.device)
            example_obs_dict[key] = this_obs
        example_output = self.forward(example_obs_dict,
                                      resnet_output_shape=resnet_output_shape)
        output_shape = example_output.shape[1:]
        return output_shape
