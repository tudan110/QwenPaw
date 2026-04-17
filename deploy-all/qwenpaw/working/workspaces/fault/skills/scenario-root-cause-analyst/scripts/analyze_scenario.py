import json


def main() -> None:
    print(
        json.dumps(
            {
                "summary": "已定位为数据库死锁导致 CMDB 新增失败",
                "rootCause": {"type": "数据库异常", "object": "cmdb_device"},
                "steps": [{"id": "database-analysis", "status": "success"}],
                "logEntries": [{"stage": "database-analysis", "summary": "捕获锁等待"}],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
