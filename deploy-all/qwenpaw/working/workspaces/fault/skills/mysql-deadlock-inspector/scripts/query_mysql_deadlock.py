import json


def main() -> None:
    print(
        json.dumps(
            {"deadlocks": [], "lockWaits": [], "transactions": []},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
