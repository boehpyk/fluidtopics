from lxml import etree
from pathlib import Path
from typing import List, Optional, BinaryIO, Iterable, Dict
from dataclasses import dataclass


FT_MAP_TMPL = """<ft:map xmlns:ft="http://ref.fluidtopics.com/v3/ft#" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="ftmap.xsd">
    <ft:toc>
    </ft:toc>
</ft:map>
"""

ftns = "{http://ref.fluidtopics.com/v3/ft#}"


@dataclass
class Topic:
    id: str
    title: str
    link: str
    content: str = ""
    metas: List = None
    sub_topics: list["Topic"] = None


class FTMap:
    """Object representing a Fluitopics Map.
    An FT map governs the way the ToC of the various topics is setup by Fluidtopics.
    See: https://doc.antidot.net/r/3.9/Upload-FTML-Content-to-Fluid-Topics/Configure-FTML-Content
    """

    def __init__(
        self,
        title: str,
        origin_id: str,
        editorial_type: str = "book",
        lang: str = "en-US",
    ):
        self.title = title
        self.origin_id = origin_id
        self.editorial_type = editorial_type
        self.lang = lang
        self.root = etree.XML(FT_MAP_TMPL)
        self.root.set(f"{ftns}lang", self.lang)
        self.root.set(f"{ftns}title", self.title)
        self.root.set(f"{ftns}originID", self.origin_id)
        self.root.set(f"{ftns}editorialType", self.editorial_type)

    def add_metas(
        self,
        toc_node: etree.Element,
        metas: Dict[str, dict],
        excluded_metas: List = ["ft:title"],
    ) -> None:
        """Add a meta in <ft:metas> for the specified toc node"""
        metasNode = etree.SubElement(toc_node, f"{ftns}metas", nsmap=self.root.nsmap)
        for metaName, metaValue in metas.items():
            if metaName in excluded_metas:
                continue
            # Handle multi-valued meta
            if type(metaValue) == list:
                for value in metaValue:
                    attributes = {"key": metaName}
                    sube = etree.SubElement(
                        metasNode,
                        f"{ftns}meta",
                        attrib=attributes,
                        nsmap=self.root.nsmap,
                    )
                    sube.text = str(value)
            else:
                attributes = {"key": metaName}
                sube = etree.SubElement(
                    metasNode, f"{ftns}meta", attrib=attributes, nsmap=self.root.nsmap
                )
                sube.text = str(metaValue)

    def get_toptoc(self) -> etree.Element:
        return self.root.xpath("//ft:toc", namespaces=self.root.nsmap)[0]

    def populate_toc_paligo(
        self,
        tocnode: etree.Element,  # TOC node to which we will add sub-elements
        current: Optional[Topic],  # current topic for recursivity
        children: Iterable[Topic],  # sub-topics for recursivity
    ) -> List[Path]:  # return the list of files that were added to the ftmap
        """Add a node and its child to the ToC"""
        collected_files = []
        if current is None:
            # no current Topic to append to the toc, will recursively add the children Topics
            tocnewnode = tocnode
        else:
            # prepare the attribute of the TOC node to create
            attributes = {f"{ftns}title": current.title}
            attributes[f"{ftns}originID"] = current.id
            attributes["href"] = current.link
            # FT cannot authorize automatic topic splitting for toc node with childs
            # see: https://doc.antidot.net/r/3.9/Upload-FTML-Content-to-Fluid-Topics/type
            if not children:
                attributes["type"] = "topics"
            collected_files.append(Path(attributes["href"]))
            tocnewnode = etree.SubElement(
                tocnode, f"{ftns}node", attrib=attributes, nsmap=self.root.nsmap
            )
            self.add_metas(tocnewnode, current.metas)

        # iterate on children
        if children is not None:
            for child in children:
                nextchilds = child.sub_topics
                collected_files.extend(
                    self.populate_toc_paligo(tocnewnode, child, nextchilds)
                )

        return collected_files

    def write(self, output: Path) -> None:
        etree.ElementTree(self.root).write(
            str(output), pretty_print=True, xml_declaration=True, encoding="utf-8"
        )
