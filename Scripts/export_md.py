from MdItem import MdItem
from md_renderer import render_md_item


def convert_md_item_to_md(item: MdItem) -> str:
    return render_md_item(item)
