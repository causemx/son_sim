import logging
import time
from libs import drone_v2x


# Configure logging with more detailed format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def main():

    def _callback(status: int, message: str):
        if status == 1:
            logging.info(f'init success, msg: {message}')
        else:
            logging.info(f'init not ready.., msg: {message}')


    drone_v2x.set_init_callback(callback=_callback)
    drone_v2x.init()

    while True:
        time.sleep(1)

if __name__ == '__main__':
    main()