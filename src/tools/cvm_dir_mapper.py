import argparse
import json
import re
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Set
from urllib.parse import urljoin, urlparse

import requests


BASE_URL = "https://dados.cvm.gov.br/dados/"
ENTITY_ROOTS = ["FIDC/", "FIP/", "FIAGRO/", "SECURIT/"]


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: List[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)


def fetch_html(url: str, timeout: int) -> str:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def extract_links(base_url: str, html: str) -> List[str]:
    parser = LinkExtractor()
    parser.feed(html)

    links: List[str] = []
    for raw_href in parser.links:
        href = raw_href.strip()
        if not href or href.startswith("?") or href.startswith("#"):
            continue
        if href.startswith("../"):
            continue
        absolute = urljoin(base_url, href)
        links.append(absolute)
    return links


def normalize_path(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path


def infer_pattern(file_name: str) -> str:
    # Converts concrete numeric names into a generalized pattern.
    # Example: inf_mensal_fidc_202502.zip -> inf_mensal_fidc_{YYYYMM}.zip
    file_name = re.sub(r"(19|20)\d{2}(0[1-9]|1[0-2])", "{YYYYMM}", file_name)
    file_name = re.sub(r"(19|20)\d{2}", "{YYYY}", file_name)
    return file_name


def crawl_entity(root_url: str, timeout: int, max_pages: int) -> Dict[str, object]:
    queue: List[str] = [root_url]
    visited: Set[str] = set()
    directories: Set[str] = set()
    files: Set[str] = set()
    errors: List[str] = []

    while queue and len(visited) < max_pages:
        current_url = queue.pop(0)
        if current_url in visited:
            continue

        visited.add(current_url)
        directories.add(normalize_path(current_url))

        try:
            html = fetch_html(current_url, timeout=timeout)
        except Exception as exc:
            errors.append(f"{current_url} -> {exc}")
            continue

        for link in extract_links(current_url, html):
            link_path = normalize_path(link)
            if not link_path.startswith(normalize_path(root_url)):
                continue

            if link.endswith("/"):
                if link not in visited:
                    queue.append(link)
            elif link.lower().endswith((".zip", ".csv")):
                files.add(link_path)

    grouped_files: Dict[str, List[str]] = defaultdict(list)
    for file_path in sorted(files):
        parent = str(Path(file_path).parent)
        grouped_files[parent].append(Path(file_path).name)

    return {
        "directories": sorted(directories),
        "files": dict(grouped_files),
        "errors": errors,
    }


def build_map(base_url: str, timeout: int, max_pages: int) -> Dict[str, object]:
    result: Dict[str, object] = {
        "base_url": base_url,
        "entities": {},
        "inferred_patterns": {},
    }

    for entity_root in ENTITY_ROOTS:
        root_url = urljoin(base_url, entity_root)
        entity_name = entity_root.rstrip("/").lower()
        crawl_result = crawl_entity(root_url, timeout=timeout, max_pages=max_pages)
        result["entities"][entity_name] = crawl_result

        patterns: Dict[str, List[str]] = {}
        for parent, file_names in crawl_result["files"].items():
            patterns[parent] = sorted({infer_pattern(name) for name in file_names})
        result["inferred_patterns"][entity_name] = patterns

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Map CVM Open Data directories and file patterns")
    parser.add_argument("--base-url", default=BASE_URL, help="CVM base URL to crawl")
    parser.add_argument("--output", default="cache/cvm_directory_map.json", help="Output JSON file path")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds")
    parser.add_argument("--max-pages", type=int, default=250, help="Maximum pages to crawl per entity")
    args = parser.parse_args()

    directory_map = build_map(args.base_url, timeout=args.timeout, max_pages=args.max_pages)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(directory_map, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"CVM directory map written to: {output_path}")
    print("Mapped entities:", ", ".join(sorted(directory_map["entities"].keys())))


if __name__ == "__main__":
    main()
