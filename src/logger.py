import logging
import os
from datetime import datetime

def setup_logging():
    
    #create log if doesn't exist
    log_folder="logs"
    os.makedirs(log_folder,exist_ok=True)
    
    log_filename= os.path.join(log_folder,f"backup_{datetime.now().strftime('%Y%m%d')}.log")
    
    log_level_str = os.environ.get("CLEAN_BACKUP_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    logging.basicConfig(
        filename=log_filename,
        level=log_level,
        # %levelname inserts the Severity Level of the log.
        # %asctime inserts the Timestamp.
        # %message inserts the actual message.
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    #print log streams to console
    console= logging.StreamHandler()
    console.setLevel(log_level)
    logging.getLogger('').addHandler(console)
    
    return logging.getLogger(__name__)

logger= setup_logging()