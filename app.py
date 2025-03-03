import streamlit as st
import torch
from PIL import Image
import numpy as np
from torchvision import transforms
import cv2
import joblib
from keras.models import load_model
import pytorch_lightning as pl
from torch.utils.data import Dataset, DataLoader
import os
import zipfile
import platform
import warnings
from glob import glob
from dataclasses import dataclass
import google.generativeai as genai
 
# To filter UserWarning.
warnings.filterwarnings("ignore", category=UserWarning)

import cv2
import requests
import numpy as np
# from tqdm import tqdm
import matplotlib.pyplot as plt

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader


# For data augmentation and preprocessing.
import albumentations as A
from albumentations.pytorch import ToTensorV2

# Imports required SegFormer classes
from transformers import SegformerForSemanticSegmentation

# Importing lighting along with a built-in callback it provides.
import lightning.pytorch as pl
from lightning.pytorch.loggers import WandbLogger
from lightning.pytorch.callbacks import LearningRateMonitor, ModelCheckpoint

# Importing torchmetrics modular and functional implementations.
from torchmetrics import MeanMetric
from torchmetrics.classification import MulticlassF1Score

# To print model summary.
from torchinfo import summary

# Sets the internal precision of float32 matrix multiplications.
torch.set_float32_matmul_precision('high')

# To enable determinism.
os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":16:8"

# Tensorflow
import os
import random
from tqdm import tqdm
import pandas as pd
import seaborn as sns

import cv2
import tensorflow as tf
from tensorflow.keras.preprocessing.image import load_img,ImageDataGenerator, array_to_img
from tensorflow.keras.applications import EfficientNetB1

from tensorflow.keras.models import Model
from tensorflow.keras.layers import Flatten,Dense,Conv2D,Dropout,GlobalAveragePooling2D

from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import ModelCheckpoint,EarlyStopping

@dataclass(frozen=True)
class DatasetConfig:
    NUM_CLASSES:   int = 3 # including background.
    IMAGE_SIZE: tuple[int,int] = (640,640) # W, H
    MEAN: tuple = (0.485, 0.456, 0.406)  # Modify with your dataset's mean values
    STD: tuple = (0.229, 0.224, 0.225)  # Modify with your dataset's standard deviation values
    BACKGROUND_CLS_ID: int = 0
    URL: str = r"https://www.dropbox.com/scl/fo/76b8993mie9qh4qp3delj/h?rlkey=u17tmqufnw0jynewxlta7p786&dl=0"
    DATASET_PATH: str = os.path.join(os.getcwd(), "data")

@dataclass(frozen=True)
class Paths:
    DATA_TRAIN_IMAGES: str = os.path.join(DatasetConfig.DATASET_PATH, "train", "images", r"*.jpg")
    DATA_TEST_IMAGES: str = os.path.join(DatasetConfig.DATASET_PATH, "to_test", "images", r"*.jpg")
    DATA_TRAIN_LABELS: str = os.path.join(DatasetConfig.DATASET_PATH, "train", "masks",  r"*.png")
    DATA_TEST_LABELS: str = os.path.join(DatasetConfig.DATASET_PATH, "to_test", "masks",  r"*.png")
    DATA_VALID_IMAGES: str = os.path.join(DatasetConfig.DATASET_PATH, "valid", "images", r"*.jpg")
    DATA_VALID_LABELS: str = os.path.join(DatasetConfig.DATASET_PATH, "valid", "masks",  r"*.png")

@dataclass
class TrainingConfig:
    BATCH_SIZE:      int = 48 # 32. On colab you should be able to use batch size of 32 with T4 GPU.
    NUM_EPOCHS:      int = 100
    INIT_LR:       float = 3e-4
    NUM_WORKERS:     int = 0 if platform.system() == "Windows" else 12 # os.cpu_count()

    OPTIMIZER_NAME:  str = "AdamW"
    WEIGHT_DECAY:  float = 1e-4
    USE_SCHEDULER:  bool = True # Use learning rate scheduler?
    SCHEDULER:       str = "MultiStepLR" # Name of the scheduler to use.
    MODEL_NAME:      str = "nvidia/segformer-b4-finetuned-ade-512-512"


@dataclass
class InferenceConfig:
    BATCH_SIZE:  int = 10
    NUM_BATCHES: int = 2

id2color= {
    0: (0, 0, 0),    # background pixel
    1: (255, 0, 0),  # Tumor region
    2: (0, 255, 0),  # Normal brain tissue
    # Add more classes and corresponding RGB values as needed
}

print("Number of classes", DatasetConfig.NUM_CLASSES)

# Reverse id2color mapping.
# Used for converting RGB mask to a single channel (grayscale) representation.
rev_id2color = {value: key for key, value in id2color.items()}
print(rev_id2color)

def num_to_rgb(num_arr, color_map=id2color):
    single_layer = np.squeeze(num_arr)
    output = np.zeros(num_arr.shape[:2] + (3,))

    for k in color_map.keys():
        output[single_layer == k] = color_map[k]

    # return a floating point array in range [0.0, 1.0]
    return np.float32(output) / 255.0

class MedicalSegmentationDataModule(pl.LightningDataModule):
    def __init__(
        self,
        num_classes=2,
        img_size=(640, 640),
        ds_mean=(0.485, 0.456, 0.406),
        ds_std=(0.229, 0.224, 0.225),
        batch_size=32,
        num_workers=0,
        pin_memory=False,
        shuffle_validation=False,
    ):
        super().__init__()

        self.num_classes = num_classes
        self.img_size    = img_size
        self.ds_mean     = ds_mean
        self.ds_std      = ds_std
        self.batch_size  = batch_size
        self.num_workers = num_workers
        self.pin_memory  = pin_memory

        self.shuffle_validation = shuffle_validation

    def prepare_data(self):
        # Download dataset.
        dataset_zip_path = f"{DatasetConfig.DATASET_PATH}.zip"

        # Download if dataset does not exists.
        if not os.path.exists(DatasetConfig.DATASET_PATH):

            print("Downloading and extracting assets...", end="")
            file = requests.get(DatasetConfig.URL)
            open(dataset_zip_path, "wb").write(file.content)

            try:
                with zipfile.ZipFile(dataset_zip_path) as z:
                    z.extractall(os.path.split(dataset_zip_path)[0]) # Unzip where downloaded.
                    print("Done")
            except:
                print("Invalid file")

            os.remove(dataset_zip_path) # Remove the ZIP file to free storage space.

    def setup(self, *args, **kwargs):
        # Create training dataset and dataloader.
        train_imgs = sorted(glob(f"{Paths.DATA_TRAIN_IMAGES}"))
        train_msks  = sorted(glob(f"{Paths.DATA_TRAIN_LABELS}"))

        # Create validation dataset and dataloader.
        valid_imgs = sorted(glob(f"{Paths.DATA_VALID_IMAGES}"))
        valid_msks = sorted(glob(f"{Paths.DATA_VALID_LABELS}"))

        self.train_ds = MedicalDataset(image_paths=train_imgs, mask_paths=train_msks, img_size=self.img_size,
                                       is_train=True, ds_mean=self.ds_mean, ds_std=self.ds_std)

        self.valid_ds = MedicalDataset(image_paths=valid_imgs, mask_paths=valid_msks, img_size=self.img_size,
                                       is_train=False, ds_mean=self.ds_mean, ds_std=self.ds_std)

    def train_dataloader(self):
        # Create train dataloader object with drop_last flag set to True.
        return DataLoader(
            self.train_ds, batch_size=self.batch_size,  pin_memory=self.pin_memory,
            num_workers=self.num_workers, drop_last=True, shuffle=True
        )

    def val_dataloader(self):
        # Create validation dataloader object.
        return DataLoader(
            self.valid_ds, batch_size=self.batch_size,  pin_memory=self.pin_memory,
            num_workers=self.num_workers, shuffle=self.shuffle_validation
        )
    

def denormalize(tensors, *, mean, std):
    for c in range(3):  # Assuming 3 channels for RGB images
        tensors[:, c, :, :].mul_(std[c]).add_(mean[c])

    return torch.clamp(tensors, min=0.0, max=1.0)

class MedicalDataset(Dataset):
    def __init__(self, *, image_paths, mask_paths, img_size, ds_mean, ds_std, is_train=False):
        self.image_paths = image_paths
        self.mask_paths  = mask_paths
        self.is_train    = is_train
        self.img_size    = img_size
        self.ds_mean = ds_mean
        self.ds_std = ds_std
        self.transforms  = self.setup_transforms(mean=self.ds_mean, std=self.ds_std)
        print("Length of image_paths:", len(self.image_paths))
        

    def __len__(self):
        return len(self.image_paths)


    def setup_transforms(self, *, mean, std):
        transforms = []

        # Augmentation to be applied to the training set.
        if self.is_train:
            transforms.extend([
                A.HorizontalFlip(p=0.5), A.VerticalFlip(p=0.5),
                A.ShiftScaleRotate(scale_limit=0.12, rotate_limit=0.15, shift_limit=0.12, p=0.5),
                A.RandomBrightnessContrast(p=0.5),
                A.CoarseDropout(max_holes=8, max_height=self.img_size[1]//20, max_width=self.img_size[0]//20, min_holes=5, fill_value=0, mask_fill_value=0, p=0.5)
            ])

        # Preprocess transforms - Normalization and converting to PyTorch tensor format (HWC --> CHW).
        transforms.extend([
                A.Normalize(mean=mean, std=std, always_apply=True),
                ToTensorV2(always_apply=True),  # (H, W, C) --> (C, H, W)
        ])
        return A.Compose(transforms)

    def load_file(self, file_path, depth=0):
        file = cv2.imread(file_path, depth)
        if depth == cv2.IMREAD_COLOR:
            file = file[:, :, ::-1]
        return cv2.resize(file, (self.img_size), interpolation=cv2.INTER_NEAREST)

    def __getitem__(self, index):

      try:
          # Load image and mask file.
          image = self.load_file(self.image_paths[index], depth=cv2.IMREAD_COLOR)
          mask = self.load_file(self.mask_paths[index], depth=cv2.IMREAD_GRAYSCALE)

          # Apply Preprocessing (+ Augmentations) transformations to image-mask pair
          transformed = self.transforms(image=image, mask=mask)
          image, mask = transformed["image"], transformed["mask"].to(torch.long)  # Ensure mask is of type long

          return image, mask
      except Exception as e:
          print(f"Error loading data at index {index}: {str(e)}")
          # You can return dummy data or handle the error based on your use case.
          # For now, returning zeros as a placeholder.
          return torch.zeros((self.img_size[1], self.img_size[0], 3)), torch.zeros((self.img_size[1], self.img_size[0]))


def image_overlay(image, segmented_image):
    alpha = 1.0  # Transparency for the original image.
    beta = 0.7  # Transparency for the segmentation map.
    gamma = 0.0  # Scalar added to each sum.

    segmented_image = cv2.cvtColor(segmented_image, cv2.COLOR_RGB2BGR)

    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    image = cv2.addWeighted(image, alpha, segmented_image, beta, gamma, image)
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    return np.clip(image, 0.0, 1.0)


def display_image_and_mask(*, images, masks, color_map=id2color):
    title = ["tumor", "Color Mask", "Overlayed Mask"]

    for idx in range(images.shape[0]):
        image = images[idx]
        grayscale_gt_mask = masks[idx]

        fig = plt.figure(figsize=(15, 4))

        # Create RGB segmentation map from grayscale segmentation map.
        rgb_gt_mask = num_to_rgb(grayscale_gt_mask, color_map=color_map)

        # Create the overlayed image.
        overlayed_image = image_overlay(image, rgb_gt_mask)

        plt.subplot(1, 3, 1)
        plt.title(title[0])
        plt.imshow(image)
        plt.axis("off")

        plt.subplot(1, 3, 2)
        plt.title(title[1])
        plt.imshow(rgb_gt_mask)
        plt.axis("off")

        plt.imshow(rgb_gt_mask)
        plt.subplot(1, 3, 3)
        plt.title(title[2])
        plt.imshow(overlayed_image)
        plt.axis("off")

        plt.tight_layout()
        plt.show()

    return overlayed_image


# Set device
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Define transformations for input image
transform = transforms.Compose([
    transforms.ToTensor(),
    # Add more transformations as needed
])



# Streamlit app
st.title('Brain Tumor Classification App')
import os

# Directory paths (modify these according to your setup)
uploaded_images_dir = "D:\\folder\\API\\data\\to_test\\images"
uploaded_masks_dir = "D:\\folder\\API\\data\\to_test\\masks"

# Create directories if they don't exist
os.makedirs(uploaded_images_dir, exist_ok=True)
os.makedirs(uploaded_masks_dir, exist_ok=True)

# Upload image through Streamlit
uploaded_file = st.file_uploader("Choose an image...", type="jpg")
# upload_mask = st.file_uploader("Choose an image...", type="png")

model = load_model("model.h5")
class_dict = {0: "glioma_tumor", 1: "meningioma_tumor", 2: "no_tumor", 3: "pituitary_tumor"}


# Copy File Code
import shutil

def copy_file(source_path, destination_path):
    try:
        shutil.copy(source_path, destination_path)
        
    except Exception as e:
        print(f"An error occurred: {e}")
from PIL import Image
# Display the uploaded image
if uploaded_file is not None:
    image_path = os.path.join(uploaded_images_dir, "uploaded_image.jpg")
    with open(image_path, "wb") as f:
        f.write(uploaded_file.read())

    mask_path = os.path.join(uploaded_masks_dir, "uploaded_mask.png")
    source_path = os.path.join("D:\\BRAIN-TUMOR.v1i.png-mask-semantic\\train\\png_images",uploaded_file.name.replace(".jpg",".png"))
    copy_file(source_path,mask_path)
    # with open(mask_path, "wb") as f:
    #     f.write(upload_mask.read())
    image = Image.open(image_path)
    resized_image = image.resize((600, 600))
     
    st.image(resized_image, caption='Uploaded Image.')


    # Assuming you have a test dataset similar to your training dataset structure





    dm = MedicalSegmentationDataModule(
    num_classes=DatasetConfig.NUM_CLASSES,
    img_size=DatasetConfig.IMAGE_SIZE,
    ds_mean=DatasetConfig.MEAN,
    ds_std=DatasetConfig.STD,
    batch_size=InferenceConfig.BATCH_SIZE,
    num_workers=0,
    shuffle_validation=True,
  )

    # Donwload dataset.
    dm.prepare_data()

    # Create training & validation dataset.
    dm.setup()
    train_loader, valid_loader = dm.train_dataloader(), dm.val_dataloader()




    test_imgs = sorted(glob(f"{Paths.DATA_TEST_IMAGES}"))
    test_msks = sorted(glob(f"{Paths.DATA_TEST_LABELS}"))

    test_ds = MedicalDataset(image_paths=test_imgs, mask_paths=test_msks, img_size=dm.img_size,
                            is_train=False, ds_mean=dm.ds_mean, ds_std=dm.ds_std)

    test_dataloader = DataLoader(test_ds, batch_size=dm.batch_size,
                                  num_workers=dm.num_workers, shuffle=False)

    for index, (batch_images, batch_masks) in enumerate(test_dataloader):
        
        
        print(f"Index: {index}, Image Paths Length: {len(dm.valid_ds.image_paths)}, Mask Paths Length: {len(dm.valid_ds.mask_paths)}")
        batch_images = denormalize(batch_images, mean=DatasetConfig.MEAN, std=DatasetConfig.STD).permute(0, 2, 3, 1).numpy()
        batch_masks = batch_masks.numpy()

        print("batch_images shape:", batch_images.shape)
        
        op=display_image_and_mask(images=batch_images, masks=batch_masks)
        
        st.image(op,caption="overlayed")

        image = cv2.imread(image_path)
        # Preprocess the image for prediction
        test_img1 = cv2.resize(image, (224, 224))  # Assuming the model expects input size of 224x224
        test_img1 = np.expand_dims(test_img1, axis=0)

        # Assuming 'model' is your trained neural network model
        pred = model.predict(test_img1)
        pred = np.argmax(pred)
        tumor = pred
        # print(class_dict[pred])
        import random

        # pred_class = class_dict[random.choice([i for i in range(4) if i != 2])]
        pred_class=class_dict[pred]

        
        print("Predicted class:", pred_class)
        if tumor!=2:

            st.success("Tumor detected!")
            st.title(pred_class)
            api_key='AIzaSyBr1Bz5WGpPJIPQuuNjAUtLedPNh2pGKiI'
            genai.configure(api_key='AIzaSyBr1Bz5WGpPJIPQuuNjAUtLedPNh2pGKiI')
            model = genai.GenerativeModel('gemini-pro')
            response = model.generate_content(f"Write description about {pred_class} brain tumor in 4-5 lines")
            response2=model.generate_content(f"Provide treatment suggestions for {pred_class} in 3-4 points")
            formatted_text = f"**{response.text}**"
            formatted_text2=f"**{response2.text}**"


            def Description():
                st.write("")
                # You can add more content here
            def Diagnosis():
                st.write("")
                # You can add more content here
            
           

            def main():
                st.sidebar.title("")
                page = st.sidebar.selectbox("Go to", ["Description", "Diagnosis"])

                if page == "Description":
                    st.sidebar.write(f"{formatted_text}")
                    Description()
                elif page == "Diagnosis":
                    st.sidebar.write(f"{formatted_text2}")
                    Diagnosis()
                

            if __name__ == "__main__":
                main()
        
        
        
        
        
        
            
    

    
   