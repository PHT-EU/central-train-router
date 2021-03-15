import os
from dotenv import load_dotenv, find_dotenv
from src.router import TrainRouter

load_dotenv(find_dotenv())

def run_train_router(query_interval: int = 10):
    router = TrainRouter()



if __name__ == '__main__':
    router = TrainRouter()
    router.run()