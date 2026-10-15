import argparse
from unittest import result


def run():
    pass


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", type=int, default=8000)
    parser.add_argument("-d", "--debug", action="store_true")


def main():

    args = parse_args()
    result = run(args)
