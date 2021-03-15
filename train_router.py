import os
from dotenv import load_dotenv, find_dotenv
from src.router import TrainRouter

load_dotenv(find_dotenv())

if __name__ == '__main__':
    router = TrainRouter()
    router.run()