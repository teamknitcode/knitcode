class Worker:
    pass


class Box:
    pass


def run(w: Worker, label="job") -> str:
    return label


def main():
    run(Worker())
    run(Box(), "first")
    batch([1, 2])
    batch([1, "wrong"])
    count_labels(["red", "blue"])
    count_labels(["red", 7])


def batch(xs: list[int]) -> int:
    return len(xs)


def count_labels(labels: list[str]) -> int:
    return len(labels)


if __name__ == "__main__":
    main()
