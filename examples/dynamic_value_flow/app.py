class Worker:
    pass


class Box:
    pass


def run(w: Worker, label="job") -> str:
    return label


def main():
    run(Worker())
    run(Box(), "first")


if __name__ == "__main__":
    main()
