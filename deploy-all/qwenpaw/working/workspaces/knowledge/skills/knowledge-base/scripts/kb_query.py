#!/usr/bin/env python3
"""Query the embedded knowledge engine without starting a server or curl."""

import argparse
import json


def main(argv=None):
    parser = argparse.ArgumentParser(description="检索知识库原文证据")
    parser.add_argument("query")
    parser.add_argument("--output", choices=["json"], default="json")
    args = parser.parse_args(argv)
    from qwenpaw.extensions.integrations.knowledge_base import query_knowledge

    print(
        json.dumps(query_knowledge({"query": args.query}), ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
