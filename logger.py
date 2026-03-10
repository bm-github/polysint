import logging

# Configure logging to write to analyzer.log (matched to your .gitignore)
logging.basicConfig(
    filename='analyzer.log',
    filemode='a', # Append mode
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.WARNING # Only logs WARNING, ERROR, and CRITICAL
)

def get_logger(name):
    return logging.getLogger(name)