import logging
import os
from datetime import datetime

def setup_logging():
    
    #create log if doesn't exist
    log_folder="logs"
    os.makedirs(log_folder,exist_ok=True)
    
    log_filename= os.path.join(log_folder,f"backup_{datetime.now().strftime('%Y%m%d')}.log")
    
    logging.basicConfig(
        filename=log_filename,
        level=logging.INFO,
        # %levelname inserts the Severity Level of the log.
        # %asctime inserts the Timestamp.
        # %message inserts the actual message.
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    #print log streams to console
    console= logging.StreamHandler()
    console.setLevel(logging.INFO)
    logging.getLogger('').addHandler(console)
    
    return logging.getLogger(__name__)

logger= setup_logging()