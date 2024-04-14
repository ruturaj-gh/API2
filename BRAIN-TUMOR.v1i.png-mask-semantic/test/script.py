import os
import shutil

def sort_and_move_images(source_folder):
    # Create destination folders if they don't exist
    os.mkdir("./jpg_images")
    os.mkdir("./png_images")
    jpg_destination_folder = os.path.join(source_folder, "jpg_images")
    png_destination_folder = os.path.join(source_folder, "png_images")
    os.makedirs(jpg_destination_folder, exist_ok=True)
    os.makedirs(png_destination_folder, exist_ok=True)

    # Get all files in source folder
    files = os.listdir(source_folder)

    # Filter files by image type
    jpg_files = [f for f in files if f.lower().endswith(".jpg")]
    png_files = [f for f in files if f.lower().endswith(".png")]

    # Sort image files
    jpg_files.sort()
    png_files.sort()

    # Rename and move JPG images
    for i, file_name in enumerate(jpg_files):
        old_path = os.path.join(source_folder, file_name)
        new_path = os.path.join(jpg_destination_folder, f"{i+1}.jpg")
        os.rename(old_path, new_path)

    # Rename and move PNG images
    for i, file_name in enumerate(png_files):
        old_path = os.path.join(source_folder, file_name)
        new_path = os.path.join(png_destination_folder, f"{i+1}.png")
        os.rename(old_path, new_path)

# Specify source folder
source_folder = "D:\\BRAIN-TUMOR.v1i.png-mask-semantic\\test"

# Sort, rename, and move images
sort_and_move_images(source_folder)

print("Images sorted, renamed, and moved to separate folders successfully.")
