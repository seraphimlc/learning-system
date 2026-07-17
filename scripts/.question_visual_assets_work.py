from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from learning_system import question_bank
from learning_system.question_visuals import QuestionVisualManifest


CHECKPOINT_ROOT = ROOT / "data/question_banks/math/.v12_pilot_six_checkpoints"
NUMBER_CHECKPOINT = CHECKPOINT_ROOT / "M-G7-NUMBER-LINE.json"
GEO_CHECKPOINT = CHECKPOINT_ROOT / "M-G7-GEO-VIEWS.json"
MANIFEST_PATH = ROOT / "data/question_visuals/math_question_visual_manifest_v1.json"
INVENTORY_PATH = ROOT / "data/question_visuals/math_question_visual_inventory_v1.json"
TEST_INVENTORY_PATH = ROOT / "tests/fixtures/question_visual_inventory_v51.json"
ITEM_VERSION = "2026-07-12.bank.v12"


def load_completed_items(path: Path) -> dict[int, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "completed" or not payload.get("completed_node_receipt"):
        raise RuntimeError(f"checkpoint is not sealed: {path}")
    if payload["completed_node_receipt"].get("question_bank_version") != ITEM_VERSION:
        raise RuntimeError(f"checkpoint item version is stale: {path}")
    items = {int(item["slot"]): item for item in payload["node"]["items"]}
    if set(items) != set(range(1, 21)) or len({item["id"] for item in items.values()}) != 20:
        raise RuntimeError(f"checkpoint does not contain 20 unique slots: {path}")
    expected = payload["completed_node_receipt"].get("item_candidate_sha256") or []
    actual = [question_bank.v12_external_candidate_sha256(items[slot]) for slot in range(1, 21)]
    if actual != expected:
        raise RuntimeError(f"checkpoint receipt digests are stale: {path}")
    return items


def profile(key: str, label: str, heights: list[int]) -> dict:
    height = max(heights)
    return {
        "key": key,
        "label": label,
        "width": len(heights),
        "height": height,
        "filled_cells": [
            [x, height - level]
            for x, value in enumerate(heights)
            for level in range(1, value + 1)
        ],
    }


def occupancy(key: str, label: str, rows: list[list[int]]) -> dict:
    return {
        "key": key,
        "label": label,
        "width": len(rows[0]),
        "height": len(rows),
        "filled_cells": [
            [x, len(rows) - 1 - row_index]
            for row_index, row in enumerate(rows)
            for x, filled in enumerate(row)
            if filled
        ],
    }


def orthographic(alt_text: str, long_description: str, views: list[dict]) -> dict:
    return {
        "scene_type": "orthographic_view",
        "alt_text": alt_text,
        "long_description": long_description,
        "scene": {"views": views},
    }


def number_line(
    alt_text: str,
    long_description: str,
    minimum: float,
    maximum: float,
    step: float,
    labeled_ticks: dict[float, str],
    points: list[tuple[str, float, str]],
) -> dict:
    tick_count = int(round((maximum - minimum) / step))
    ticks = []
    for index in range(tick_count + 1):
        value = maximum if index == tick_count else round(minimum + index * step, 10)
        label = labeled_ticks.get(value, "·")
        ticks.append({"value": value, "label": label})
    return {
        "scene_type": "number_line",
        "alt_text": alt_text,
        "long_description": long_description,
        "scene": {
            "axis": {
                "min": minimum,
                "max": maximum,
                "step": step,
                "origin": 0,
                "direction": "right",
            },
            "ticks": ticks,
            "points": [
                {"key": key, "value": value, "label": label}
                for key, value, label in points
            ],
        },
    }


def number_line_scene_catalog() -> dict[str, dict]:
    scenes = [
        number_line(
            "数轴上标出负三、零和二的位置。",
            "数轴向右为正方向，负三在零左侧三个单位，二在零右侧两个单位。",
            -4, 3, 1, {-3: "−3", 0: "0", 2: "2"}, [("negative-three", -3, "−3"), ("positive-two", 2, "2")],
        ),
        number_line(
            "数轴标出零、一和零左侧的一个未知点。",
            "零和一给出方向与单位参照；未知点在零左侧，但图中没有给它写数值。",
            -3, 2, 1, {0: "0", 1: "1"}, [("unknown-left", -2, "? ")],
        ),
        number_line(
            "数轴上A在零左边三格，B在零右边两格。",
            "每格表示一，A、B只标字母，孩子需要根据方向、格数和左右位置读数并比较。",
            -4, 3, 1, {0: "0"}, [("a", -3, "A"), ("b", 2, "B")],
        ),
        number_line(
            "每格零点五的数轴上标出A和B。",
            "A在零左边四格，B在零右边三格；零是已知参照，点旁只显示字母。",
            -2.5, 2, 0.5, {0: "0"}, [("a", -2, "A"), ("b", 1.5, "B")],
        ),
        number_line(
            "零到一分成三格的数轴上标出M和N。",
            "M在零左边第二格，N在一右边第一格；零和一已标出。",
            -1, 5 / 3, 1 / 3, {0: "0", 1: "1"}, [("m", -2 / 3, "M"), ("n", 4 / 3, "N")],
        ),
        number_line(
            "零到一分成两格的数轴上标出P。",
            "P在零左边第三小格，零和一给出每格大小，点旁只显示P。",
            -2, 1, 0.5, {0: "0", 1: "1"}, [("p", -1.5, "P")],
        ),
        number_line(
            "只有零和第三个刻度点P的直线。",
            "直线向右为正，P在零右边第三个等距刻度处，但图和题目都没有声明每格代表多少。",
            0, 4, 1, {0: "0"}, [("p", 3, "P")],
        ),
        number_line(
            "每格零点二的数轴上标出R和S。",
            "R在零左边三格，S在零右边四格，点旁只标字母。",
            -0.8, 1, 0.2, {0: "0"}, [("r", -0.6, "R"), ("s", 0.8, "S")],
        ),
        number_line(
            "温度读数转换成以零为原点的数轴。",
            "每格表示零点五摄氏度，P在零的负方向五格，Q在正方向三格。",
            -3, 2, 0.5, {0: "0℃"}, [("p", -2.5, "P"), ("q", 1.5, "Q")],
        ),
        number_line(
            "零到一分成四格的数轴上标出T。",
            "T位于零左边第三小格；零和一给出单位长度，点旁只显示T。",
            -1, 0.5, 0.25, {0: "0", 0.5: "0.5"}, [("t", -0.75, "T")],
        ),
        number_line(
            "每格零点二五的数轴上标出P。",
            "P在零左边第六格，孩子需要用候选数反向检验格数。",
            -2, 0.5, 0.25, {0: "0"}, [("p", -1.5, "P")],
        ),
        number_line(
            "每格一的数轴上标出零两侧等距的两个目标位置。",
            "两个目标点都离零两格，一个在左侧，一个在右侧，点旁不写数值。",
            -3, 3, 1, {0: "0"}, [("left-target", -2, "左点"), ("right-target", 2, "右点")],
        ),
        number_line(
            "以警戒线为零的水位数轴。",
            "上午点在零右侧零点四处，下午点在零左侧零点六处；正方向表示高于警戒线。",
            -1, 1, 0.2, {0: "警戒线0"}, [("morning", 0.4, "上午"), ("afternoon", -0.6, "下午")],
        ),
        number_line(
            "以学校门口为零、每格两米的东西方向数轴。",
            "A在零西侧三格，B在零东侧两格；向东即向右为正方向。",
            -8, 6, 2, {0: "学校0"}, [("a", -6, "A"), ("b", 4, "B")],
        ),
        number_line(
            "每格零点四的数轴上标出Q。",
            "Q在零左边五格，点旁只显示Q，孩子需要结合方向和单位长度读数。",
            -2.4, 0.8, 0.4, {0: "0"}, [("q", -2, "Q")],
        ),
        number_line(
            "零到一分成五格的数轴上标出M。",
            "M在零左边第四小格，零和一确定单位长度，点旁只显示M。",
            -1, 1, 0.2, {0: "0", 1: "1"}, [("m", -0.8, "M")],
        ),
        number_line(
            "每格一的数轴上标出C和D。",
            "C在零左边五格，D在零右边两格，用来区分到零的距离和数的大小。",
            -6, 3, 1, {0: "0"}, [("c", -5, "C"), ("d", 2, "D")],
        ),
        number_line(
            "零到一分成八格的数轴上标出E和F。",
            "E在零左边五格，F在零右边六格，点旁只标字母。",
            -0.75, 0.875, 0.125, {0: "0"}, [("e", -0.625, "E"), ("f", 0.75, "F")],
        ),
        number_line(
            "从A到B平均分成十格的数轴。",
            "A表示负一点二，B表示零点八，零的刻度已标出，孩子需要说明每格大小和从A到零的格数。",
            -1.2, 0.8, 0.2, {-1.2: "−1.2", 0: "0", 0.8: "0.8"}, [("a", -1.2, "A"), ("b", 0.8, "B")],
        ),
        number_line(
            "零到一分成四格的数轴上标出X和Y。",
            "X在零左边第五小格，Y在一右边第二小格，点旁只标字母。",
            -1.5, 1.75, 0.25, {0: "0", 1: "1"}, [("x", -1.25, "X"), ("y", 1.5, "Y")],
        ),
    ]
    return {
        f"QB12-M-G7-NUMBER-LINE-{slot:02d}": scene
        for slot, scene in enumerate(scenes, start=1)
    }


def cube_net(alt_text: str, long_description: str, coordinates: list[tuple[str, int, int]]) -> dict:
    return {
        "scene_type": "cube_net",
        "alt_text": alt_text,
        "long_description": long_description,
        "scene": {
            "cells": [
                {"key": key.lower(), "x": x, "y": y, "label": key}
                for key, x, y in coordinates
            ]
        },
    }


def number_line_scene(
    alt_text: str,
    long_description: str,
    minimum: float,
    maximum: float,
    step: float,
    ticks: list[tuple[float, str]],
    points: list[tuple[str, float, str]],
) -> dict:
    return {
        "scene_type": "number_line",
        "alt_text": alt_text,
        "long_description": long_description,
        "scene": {
            "axis": {
                "min": minimum,
                "max": maximum,
                "step": step,
                "origin": 0,
                "direction": "right",
            },
            "ticks": [{"value": value, "label": label} for value, label in ticks],
            "points": [{"key": key, "value": value, "label": label} for key, value, label in points],
        },
    }


def number_scene_catalog() -> dict[int, dict]:
    return {
        1: number_line_scene("数轴上标出负三和二。", "0为原点，向右为正方向，每格表示1；负三在0左边三格，二在0右边两格。", -3, 2, 1, [(-3,"-3"),(-2,"-2"),(-1,"-1"),(0,"0"),(1,"1"),(2,"2")], [("negative",-3,"-3"),("positive",2,"2")]),
        2: number_line_scene("标有0和1并向左延伸的数轴。", "0到1确定一个单位长度；0左边还包含多个不同位置，仅知道在左边不能确定具体数。", -3, 1, 1, [(-3,"左3格"),(-2,"左2格"),(-1,"左1格"),(0,"0"),(1,"1")], []),
        3: number_line_scene("点A在负三，点B在二的数轴。", "0为原点，向右为正方向，每格表示1；A在0左边三格，B在0右边两格。", -3, 2, 1, [(-3,"-3"),(-2,"-2"),(-1,"-1"),(0,"0"),(1,"1"),(2,"2")], [("a",-3,"A"),("b",2,"B")]),
        4: number_line_scene("点A在负二，点B在一点五的数轴。", "每格表示0.5；A在0左边四格，B在0右边三格。", -2, 1.5, .5, [(-2,"-2"),(-1.5,"-1.5"),(-1,"-1"),(-.5,"-0.5"),(0,"0"),(.5,"0.5"),(1,"1"),(1.5,"1.5")], [("a",-2,"A"),("b",1.5,"B")]),
        5: number_line_scene("三等分单位长度的数轴上标出M和N。", "0到1平均分成三格；M在0左边第二格，N在1右边第一格。", -1, 4/3, 1/3, [(-1,"-1"),(-2/3,"-2/3"),(-1/3,"-1/3"),(0,"0"),(1/3,"1/3"),(2/3,"2/3"),(1,"1"),(4/3,"4/3")], [("m",-2/3,"M"),("n",4/3,"N")]),
        6: number_line_scene("二等分单位长度的数轴上点P在0左边三格。", "0到1平均分成两格，每格是0.5；P在0左边第三格。", -1.5, 1, .5, [(-1.5,"左3格"),(-1,"左2格"),(-.5,"左1格"),(0,"0"),(.5,"半格"),(1,"1")], [("p",-1.5,"P")]),
        7: number_line_scene("只有0和刻度位置的数轴，P在右边第三个刻度。", "图上标出0和向右的三个刻度，但没有给出每格表示多少；P位于第三个刻度。", 0, 3, 1, [(0,"0"),(1,"第1格"),(2,"第2格"),(3,"第3格")], [("p",3,"P")]),
        8: number_line_scene("每格零点二的数轴上标出R和S。", "R在0左边三格，S在0右边四格；每格表示0.2。", -.6, .8, .2, [(-.6,"-0.6"),(-.4,"-0.4"),(-.2,"-0.2"),(0,"0"),(.2,"0.2"),(.4,"0.4"),(.6,"0.6"),(.8,"0.8")], [("r",-.6,"R"),("s",.8,"S")]),
        9: number_line_scene("从低温到高温的温度刻度上标出P和Q。", "刻度由左到右表示温度升高，每格0.5摄氏度；P对应0下方五格，Q对应0上方三格。", -2.5, 1.5, .5, [(-2.5,"下5格"),(-2,"-2"),(-1.5,"-1.5"),(-1,"-1"),(-.5,"-0.5"),(0,"0℃"),(.5,"0.5"),(1,"1"),(1.5,"上3格")], [("p",-2.5,"P"),("q",1.5,"Q")]),
        10: number_line_scene("四等分单位长度的数轴上标出点T。", "0到1平均分成四格，每格0.25；T在0左边三格。", -1, 1, .25, [(-1,"-1"),(-.75,"-3/4"),(-.5,"-1/2"),(-.25,"-1/4"),(0,"0"),(.25,"1/4"),(.5,"1/2"),(.75,"3/4"),(1,"1")], [("t",-.75,"T")]),
        11: number_line_scene("每格零点二五的数轴上点P位于0左边六格。", "P的实际位置是0左边六个0.25；图中另标出小雨所说的负一点二五位置用于反查。", -1.5, 0, .25, [(-1.5,"左6格"),(-1.25,"-1.25?"),(-1,"-1"),(-.75,"-0.75"),(-.5,"-0.5"),(-.25,"-0.25"),(0,"0")], [("p",-1.5,"P"),("claim",-1.25,"小雨读数")]),
        12: number_line_scene("数轴上标出负二和二。", "0为原点，每格表示1；负二和二到0距离相同、方向相反。", -2, 2, 1, [(-2,"-2"),(-1,"-1"),(0,"0"),(1,"1"),(2,"2")], [("negative",-2,"-2"),("positive",2,"2")]),
        13: number_line_scene("以警戒线为0的水位数轴上标出上午和下午。", "高于警戒线为正，低于警戒线为负；上午点在正0.4，下午点在负0.6。", -.6, .4, .2, [(-.6,"-0.6米"),(-.4,"-0.4"),(-.2,"-0.2"),(0,"警戒线0"),(.2,"0.2"),(.4,"+0.4米")], [("morning",.4,"上午"),("afternoon",-.6,"下午")]),
        14: number_line_scene("东西方向小路数轴上标出A和B。", "学校门口为0，向东为正，每格2米；A在西边三格，B在东边两格。", -6, 4, 2, [(-6,"西3格"),(-4,"西2格"),(-2,"西1格"),(0,"学校0"),(2,"东1格"),(4,"东2格")], [("a",-6,"A"),("b",4,"B")]),
        15: number_line_scene("每格零点四的数轴上点Q位于0左边五格。", "0为原点，向右为正，每格0.4；Q在0左边第五格。", -2, .4, .4, [(-2,"左5格"),(-1.6,"左4格"),(-1.2,"左3格"),(-.8,"左2格"),(-.4,"左1格"),(0,"0"),(.4,"右1格")], [("q",-2,"Q")]),
        16: number_line_scene("五等分单位长度的数轴上点M位于0左边四格。", "0到1平均分成五格，每格五分之一；M在0左边第四格。", -.8, 1, .2, [(-.8,"左4格"),(-.6,"左3格"),(-.4,"左2格"),(-.2,"左1格"),(0,"0"),(.2,"1/5"),(.4,"2/5"),(.6,"3/5"),(.8,"4/5"),(1,"1")], [("m",-.8,"M")]),
        17: number_line_scene("点C在负五，点D在二的数轴。", "每格表示1；C在0左边五格，D在0右边两格。", -5, 2, 1, [(-5,"-5"),(-4,"-4"),(-3,"-3"),(-2,"-2"),(-1,"-1"),(0,"0"),(1,"1"),(2,"2")], [("c",-5,"C"),("d",2,"D")]),
        18: number_line_scene("八等分单位长度的数轴上标出E和F。", "0到1平均分成八格；E在0左边五格，F在0右边六格。", -5/8, 1, 1/8, [(-5/8,"-5/8"),(-.5,"-4/8"),(-.375,"-3/8"),(-.25,"-2/8"),(-.125,"-1/8"),(0,"0"),(.125,"1/8"),(.25,"2/8"),(.375,"3/8"),(.5,"4/8"),(.625,"5/8"),(.75,"6/8"),(.875,"7/8"),(1,"1")], [("e",-5/8,"E"),("f",.75,"F")]),
        19: number_line_scene("A到B被十等分的数轴。", "A表示负一点二，B表示零点八，A到B分成十个相等小格；中间刻度未直接标出0。", -1.2, .8, .2, [(-1.2,"A=-1.2"),(-1,"·"),(-.8,"·"),(-.6,"·"),(-.4,"·"),(-.2,"·"),(0,"·"),(.2,"·"),(.4,"·"),(.6,"·"),(.8,"B=0.8")], [("a",-1.2,"A"),("b",.8,"B")]),
        20: number_line_scene("四等分单位长度的数轴上标出X和Y。", "0到1平均分成四格；X在0左边第五格，Y在1右边第二格。", -1.25, 1.5, .25, [(-1.25,"左5格"),(-1,"-1"),(-.75,"-3/4"),(-.5,"-1/2"),(-.25,"-1/4"),(0,"0"),(.25,"1/4"),(.5,"1/2"),(.75,"3/4"),(1,"1"),(1.25,"1右1格"),(1.5,"1右2格")], [("x",-1.25,"X"),("y",1.5,"Y")]),
    }


def geo_scene_catalog() -> dict[int, dict]:
    return {
        1: cube_net(
            "六个标有A到F的正方形组成两排图形。",
            "上排从左到右是A、B、C、D四个连续正方形；B和C的正下方分别连接E和F。",
            [("A", 0, 0), ("B", 1, 0), ("C", 2, 0), ("D", 3, 0), ("E", 1, 1), ("F", 2, 1)],
        ),
        2: orthographic(
            "小正方体组合的前排和后排高度记录。",
            "前排左、中、右三列高度是1、2、1；后排只有中间一列，高度是1。请据此判断正面和上面视图。",
            [profile("front-row", "前排高度 1,2,1", [1, 2, 1]), profile("back-row", "后排高度 0,1,0", [0, 1, 0])],
        ),
        3: cube_net(
            "以A为中心并标有A到F的六面展开图。",
            "A在中间，B在A上方，C在A下方，D在A左边，E在A右边，F在E右边。",
            [("A", 1, 1), ("B", 1, 0), ("C", 1, 2), ("D", 0, 1), ("E", 2, 1), ("F", 3, 1)],
        ),
        4: orthographic(
            "三列两排小正方体的前排和后排高度记录。",
            "前排左、中、右高度为1、2、1；后排左、中、右高度为2、1、0。请由两排高度求三视图。",
            [profile("front-row", "前排高度 1,2,1", [1, 2, 1]), profile("back-row", "后排高度 2,1,0", [2, 1, 0])],
        ),
        5: orthographic(
            "三列两排小正方体的高度记录。",
            "前排左、中、右高度为1、2、1；后排左、中、右高度为0、1、2。请据此画出上面视图。",
            [profile("front-row", "前排高度 1,2,1", [1, 2, 1]), profile("back-row", "后排高度 0,1,2", [0, 1, 2])],
        ),
        6: orthographic(
            "两列两排小正方体的高度记录。",
            "前排左、右高度为2、1；后排左、右高度为1、3。请从左面观察每一排的最高轮廓。",
            [profile("front-row", "前排左右 2,1", [2, 1]), profile("back-row", "后排左右 1,3", [1, 3])],
        ),
        7: orthographic(
            "给定的正面视图和左面视图都由两个并排方格组成。",
            "正面视图左右两列高度都是1；左面视图前后两列高度都是1。题目要求判断这些视图是否唯一确定小正方体个数。",
            [profile("front", "给定正面视图", [1, 1]), profile("left", "给定左面视图", [1, 1])],
        ),
        8: orthographic(
            "甲、A、B三个立体的六个底面位置高度记录。",
            "每幅图从左到右依次记录前左、后左、前中、后中、前右、后右六个高度。甲为2、1、1、3、1、0；A为1、2、2、1、1、1；B为2、0、2、3、0、1。",
            [profile("shape-jia", "甲 前后成对", [2, 1, 1, 3, 1, 0]), profile("shape-a", "A 前后成对", [1, 2, 2, 1, 1, 1]), profile("shape-b", "B 前后成对", [2, 0, 2, 3, 0, 1])],
        ),
        9: orthographic(
            "两列两排小正方体的高度记录。",
            "前排左、右高度为3、1；后排左、右高度为2、4。请把左右方向压缩后判断右面视图。",
            [profile("front-row", "前排左右 3,1", [3, 1]), profile("back-row", "后排左右 2,4", [2, 4])],
        ),
        10: orthographic(
            "两列两排小正方体的高度记录。",
            "前排左、右高度为1、3；后排左、右高度为2、1。请比较两种求右面视图的方法。",
            [profile("front-row", "前排左右 1,3", [1, 3]), profile("back-row", "后排左右 2,1", [2, 1])],
        ),
        11: cube_net(
            "标有A到F的六面正方体展开图。",
            "第二行从左到右为A、B、C、D；E接在B上方，F接在C下方。",
            [("A", 0, 1), ("B", 1, 1), ("C", 2, 1), ("D", 3, 1), ("E", 1, 0), ("F", 2, 2)],
        ),
        12: orthographic(
            "两列两排小正方体的高度记录。",
            "前排左、右高度为1、3；后排左、右高度为2、1。请判断从正面看应按左右列还是前后排记录。",
            [profile("front-row", "前排左右 1,3", [1, 3]), profile("back-row", "后排左右 2,1", [2, 1])],
        ),
        13: {
            "scene_type": "simple_geometry",
            "alt_text": "依次画出纸片正面、三角形图案、线段和线框立方体四个对象。",
            "long_description": "图中用闭合长方形表示①纸片正面，用三角形表示②三角形图案，用一条线段表示④铅笔边缘，用前后错开的两个正方形及连接边表示③魔方。",
            "scene": {
                "points": [
                    {"key": "p1", "x": 5, "y": 15, "label": "①"}, {"key": "p2", "x": 25, "y": 15, "label": "·"}, {"key": "p3", "x": 25, "y": 38, "label": "·"}, {"key": "p4", "x": 5, "y": 38, "label": "·"},
                    {"key": "t1", "x": 35, "y": 38, "label": "②"}, {"key": "t2", "x": 45, "y": 15, "label": "·"}, {"key": "t3", "x": 55, "y": 38, "label": "·"},
                    {"key": "l1", "x": 5, "y": 65, "label": "④"}, {"key": "l2", "x": 25, "y": 65, "label": "·"},
                    {"key": "c1", "x": 65, "y": 25, "label": "③"}, {"key": "c2", "x": 82, "y": 25, "label": "·"}, {"key": "c3", "x": 82, "y": 45, "label": "·"}, {"key": "c4", "x": 65, "y": 45, "label": "·"},
                    {"key": "c5", "x": 73, "y": 15, "label": "·"}, {"key": "c6", "x": 90, "y": 15, "label": "·"}, {"key": "c7", "x": 90, "y": 35, "label": "·"}, {"key": "c8", "x": 73, "y": 35, "label": "·"}
                ],
                "segments": [
                    {"from": "p1", "to": "p2"}, {"from": "p2", "to": "p3"}, {"from": "p3", "to": "p4"}, {"from": "p4", "to": "p1"},
                    {"from": "t1", "to": "t2"}, {"from": "t2", "to": "t3"}, {"from": "t3", "to": "t1"}, {"from": "l1", "to": "l2"},
                    {"from": "c1", "to": "c2"}, {"from": "c2", "to": "c3"}, {"from": "c3", "to": "c4"}, {"from": "c4", "to": "c1"},
                    {"from": "c5", "to": "c6"}, {"from": "c6", "to": "c7"}, {"from": "c7", "to": "c8"}, {"from": "c8", "to": "c5"},
                    {"from": "c1", "to": "c5"}, {"from": "c2", "to": "c6"}, {"from": "c3", "to": "c7"}, {"from": "c4", "to": "c8"}
                ],
                "markers": [],
            },
        },
        14: orthographic(
            "三列两排小正方体的高度记录。",
            "前排左、中、右高度为2、0、1；后排左、中、右高度为1、3、2。请据此求正面视图并判断所得图形类别。",
            [profile("front-row", "前排高度 2,0,1", [2, 0, 1]), profile("back-row", "后排高度 1,3,2", [1, 3, 2])],
        ),
        15: orthographic(
            "三列两排小正方体的高度记录。",
            "前排左、中、右高度为0、2、1；后排左、中、右高度为3、1、2。请据此判断正确的正面记录方法。",
            [profile("front-row", "前排高度 0,2,1", [0, 2, 1]), profile("back-row", "后排高度 3,1,2", [3, 1, 2])],
        ),
        16: orthographic(
            "两列三排小正方体的高度记录。",
            "前排左、右高度为2、0；中排为1、3；后排为0、1。请用占位而不是高度总和画上面视图。",
            [profile("front-row", "前排左右 2,0", [2, 0]), profile("middle-row", "中排左右 1,3", [1, 3]), profile("back-row", "后排左右 0,1", [0, 1])],
        ),
        17: cube_net(
            "五个连续正方形加一个上方正方形组成的图形。",
            "第一行从左到右为A、B、C、D、E五个连续正方形，F接在C的上边。",
            [("A", 0, 1), ("B", 1, 1), ("C", 2, 1), ("D", 3, 1), ("E", 4, 1), ("F", 2, 0)],
        ),
        18: orthographic(
            "给定的上面视图和正面视图约束。",
            "上面视图前排左中右和后排左右有方格，后排中间为空；正面视图左中右三列高度为2、1、3。请给出一种符合条件的搭法。",
            [occupancy("top", "给定上面视图", [[1, 1, 1], [1, 0, 1]]), profile("front", "给定正面视图", [2, 1, 3])],
        ),
        19: orthographic(
            "给定的上面、正面和左面三视图约束。",
            "上面视图占前左、前中、后中、后右四格；正面左中右高度为2、3、1；左面前后高度为2、3。",
            [occupancy("top", "给定上面视图", [[1, 1, 0], [0, 1, 1]]), profile("front", "给定正面视图", [2, 3, 1]), profile("left", "给定左面视图", [2, 3])],
        ),
        20: orthographic(
            "三列两排小正方体的高度记录。",
            "前排左、中、右高度为2、0、1；后排左、中、右高度为1、3、0。请比较正面与上面视图，并判断正面视图能否唯一决定上面视图。",
            [profile("front-row", "前排高度 2,0,1", [2, 0, 1]), profile("back-row", "后排高度 1,3,0", [1, 3, 0])],
        ),
    }


def main() -> None:
    number_checkpoint = json.loads(NUMBER_CHECKPOINT.read_text(encoding="utf-8"))
    number_complete = number_checkpoint.get("status") == "completed"
    number_items = load_completed_items(NUMBER_CHECKPOINT) if number_complete else {}
    geo_items = load_completed_items(GEO_CHECKPOINT)
    number_scenes = number_line_scene_catalog()
    if number_complete and set(number_scenes) != {item["id"] for item in number_items.values()}:
        raise RuntimeError("number-line scene inventory is incomplete")

    geo_scenes = geo_scene_catalog()
    entries = []
    inventory_groups = []
    if not number_complete:
        inventory_groups.append({
            "node_id": "M-G7-NUMBER-LINE",
            "checkpoint_status": "refresh_pending",
            "item_version": ITEM_VERSION,
            "items": [
                {
                    "slot": slot,
                    "question_id": f"QB12-M-G7-NUMBER-LINE-{slot:02d}",
                    "binding_status": "refresh_pending",
                    "required": True,
                    "scene_type": "number_line",
                }
                for slot in range(1, 21)
            ],
        })

    sources = [("M-G7-GEO-VIEWS", geo_items, geo_scenes)]
    if number_complete:
        sources.insert(0, ("M-G7-NUMBER-LINE", number_items, number_scenes))
    for node_id, items, scenes in sources:
        inventory_items = []
        for slot in range(1, 21):
            item = items[slot]
            scene = scenes[item["id"]] if node_id == "M-G7-NUMBER-LINE" else scenes[slot]
            digest = question_bank.v12_external_candidate_sha256(item)
            entry = {
                "question_id": item["id"],
                "item_version": ITEM_VERSION,
                "question_digest_sha256": digest,
                "required": True,
                **scene,
            }
            QuestionVisualManifest.validate_entry(entry)
            entries.append(entry)
            inventory_items.append({
                "slot": slot,
                "question_id": item["id"],
                "question_digest_sha256": digest,
                "required": True,
                "scene_type": scene["scene_type"],
            })
        inventory_groups.append({
            "node_id": node_id,
            "checkpoint_status": "complete",
            "item_version": ITEM_VERSION,
            "items": inventory_items,
        })

    inventory = {
        "schema_version": "question-visual-inventory.v1",
        "inventory_version": "2026-07-15.number-line-geo-views.v2",
        "allowed_scene_types": ["number_line", "cube_net", "orthographic_view", "simple_geometry"],
        "groups": inventory_groups,
    }
    manifest = {
        "schema_version": "question-visual-manifest.v1",
        "manifest_version": "2026-07-15.math-number-line-geo-views.v2",
        "inventory_relative_path": "data/question_visuals/math_question_visual_inventory_v1.json",
        "renderer_contract_version": "question-visual-renderer.v1",
        "entries": entries,
    }
    QuestionVisualManifest._validate_inventory(inventory)
    INVENTORY_PATH.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TEST_INVENTORY_PATH.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    QuestionVisualManifest.load_validated(MANIFEST_PATH, inventory_path=INVENTORY_PATH)
    print(json.dumps({
        "manifest_entries": len(entries),
        "inventory_slots": 40,
        "number_line_status": "complete" if number_complete else "refresh_pending",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
