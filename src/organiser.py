import shutil
from pathlib import Path
from src import constants
from src.metadata import get_image_date, get_video_date, get_file_modification_date
from src.logger import logger

def organise_files(src_dir,dest_dir):
    src_path= Path(src_dir)
    dest_path= Path(dest_dir)
    
    for file_path in src_path.rglob('*'): #recursive glob search 
        if file_path.is_file():
            ext = file_path.suffix.lower()
            
            #get date
            date_taken=None
            
            if ext in constants.IMAGE_EXTENSIONS:
                date_taken = get_image_date(str(file_path))
            elif ext in constants.VIDEO_EXTENSIONS:
                date_taken = get_video_date(str(file_path))
            
            #if date not available assign current system date
            if date_taken is None:
                date_taken=  get_file_modification_date(str(file_path))
                logger.info(f"Used current file system date for: {file_path.name}")
                
            #create target dest
            year_folder= date_taken.strftime('%Y')
            month_folder= date_taken.strftime('%B')
            
            target_folder =dest_path/year_folder/month_folder
            target_folder.mkdir(parents=True,exist_ok=True)
            
            target_file = target_folder / file_path.name

            #move to target dest
            if target_file.exists():
                logger.info(f"Skipped duplicate: {file_path.name} already exists in {target_folder}")
            else:
                try:
                    shutil.move(str(file_path), str(target_file))
                    logger.info(f"Moved: {file_path.name} -> {target_folder}")
                except Exception as e:
                    logger.error(f"Error moving {file_path.name}: {e}")

if __name__ == "__main__":
    # Example usage
    source = input("Enter source folder path: ")
    destination = input("Enter destination folder path: ")
    organise_files(source, destination)