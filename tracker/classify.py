"""品名判斷：格式（黑膠/7吋/CD/卡帶）、類型（動畫/遊戲 × 原聲/歌曲/改編）、版本標籤、作品、是否日系、相關性。"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------- 格式
# 「卡帶」在台灣也指遊戲卡匣：只有搭配音樂字眼、且沒有主機名稱時才算錄音帶
CASSETTE_STRONG_RE = re.compile(r"錄音帶|cassette|カセットテープ|カセット|磁帶(?!.*黑膠)|\bMC\b(?=.*(?:原聲|サウンド|Soundtrack))", re.I)
CASSETTE_WEAK_RE = re.compile(r"卡帶|\bTAPE\b", re.I)
MUSIC_WORD_RE = re.compile(r"原聲|音樂|專輯|OST|O\.S\.T|Soundtrack|サウンド|サントラ|主題曲|歌曲|唱片|アルバム|Album", re.I)
CONSOLE_RE = re.compile(r"遊戲片|遊戲卡|游戲卡|卡匣|卡帶盒|Switch|\bNS2?\b|\bSFC\b|\bFC\b|紅白機|超任|超級任天堂|\bGBA?\b|GAME ?BOY|"
                        r"\bPSP\b|\bPSV\b|\bPS[1-5]\b|3DS|\bNDS\b|\bMD\b|MEGA ?DRIVE|PC ?ENGINE|N64|原裝日卡|日卡|裸卡|裸片|"
                        r"Masking|smartphone|閃卡|卡貼|Plastic Model", re.I)


def _is_cassette(t: str) -> bool:
    if CONSOLE_RE.search(t):
        return False
    return bool(CASSETTE_STRONG_RE.search(t) or (CASSETTE_WEAK_RE.search(t) and MUSIC_WORD_RE.search(t)))
SEVEN_RE = re.compile(r"7\s?吋|7\s?寸|7\s?(?:\"|”|″|''|inch|インチ)|\b7inch\b|EP黑膠|單曲黑膠|7\" Vinyl", re.I)
VINYL_RE = re.compile(
    r"黑膠|彩膠|膠唱片|畫膠|\bLPs?\b|\d\s?LP|LP盤|レコード|アナログ|vinyl|10\s?吋|12\s?吋|12\"|10\"|Picture Disc", re.I)
CD_RE = re.compile(r"(?<![A-Z])CD(?![A-Z])|\dCD|SACD|UHQCD|Blu-spec|BSCD2|SHM-CD|光碟|コンパクトディスク", re.I)
BOX_RE = re.compile(r"\bBOX\b|BOX SET|Boxset|套裝|ボックス|BOX\)", re.I)

FORMAT_LABEL = {"vinyl": "黑膠 LP", "7inch": "7 吋黑膠", "cd": "CD", "cassette": "卡帶"}


def detect_format(title: str, hint: str | None = None) -> str | None:
    """回傳 vinyl / 7inch / cd / cassette；判斷不出來回傳 hint（通路分類）或 None。"""
    t = title
    if not VINYL_RE.search(t) and _is_cassette(t):
        return "cassette"
    if hint == "cassette" and not CONSOLE_RE.search(t):
        return "cassette"
    if SEVEN_RE.search(t):
        return "7inch"
    if VINYL_RE.search(t):
        return "vinyl"
    if CD_RE.search(t):
        return "cd"
    return hint


def disc_count(title: str) -> str:
    m = re.search(r"(\d{1,2})\s?(?:LP|CD)s?\b", title, re.I) or re.search(r"(\d{1,2})\s?(?:枚組|張組|片裝|碟)", title)
    return f"{m.group(1)}" if m else ""


# ---------------------------------------------------------------- 類型
GAME_RE = re.compile(r"遊戲|電玩|游戏|ゲーム|video ?game|game soundtrack|\bVGM\b|\bGame\b(?! of Thrones)|任天堂|Nintendo|"
                     r"SQUARE ENIX|CAPCOM|SEGA|ATLUS|KONAMI|Falcom|PlayStation|Xbox", re.I)
ANIME_RE = re.compile(r"動畫|動漫|アニメ|anime|劇場版|TV動畫|電視動畫|番劇|OVA|吉卜力|Ghibli|ジブリ", re.I)
SONG_RE = re.compile(r"主題曲|主題歌|角色歌|キャラクターソング|キャラソン|歌曲集|歌曲輯|歌曲精選|ソング|Theme Song|"
                     r"Opening|Ending|\bOP\b|\bED\b|單曲|シングル|Single|Best Collection|ベスト", re.I)
ARRANGE_RE = re.compile(r"交響|Symphon|Orchestra|オーケストラ|管弦|鋼琴|ピアノ|Piano|爵士|Jazz|Arrange|アレンジ|Lo-?Fi|"
                        r"Acoustic|演奏會|音樂會|Concert|Live|ライブ|Cover|翻唱|八音盒|Music Box|オルゴール", re.I)
OST_RE = re.compile(r"原聲|原聲帶|配樂|サウンドトラック|サントラ|soundtrack|O\.?S\.?T\.?|\bScore\b|劇伴|音楽集|音樂集", re.I)


def detect_kind(text: str, franchise_kind: str | None) -> str:
    """anime / game / other"""
    if franchise_kind == "game" or GAME_RE.search(text):
        return "game"
    if franchise_kind in ("anime", "studio") or ANIME_RE.search(text):
        return "anime"
    return "anime" if franchise_kind == "composer" else "other"


def detect_sub(title: str) -> str:
    """ost / song / arrange"""
    if ARRANGE_RE.search(title):
        return "arrange"
    if SONG_RE.search(title) and not OST_RE.search(title):
        return "song"
    return "ost"


# ---------------------------------------------------------------- 版本標籤
TAG_RULES = [
    ("限定盤", r"限定|初回|Limited|完全生産|完全生產|數量限定|数量限定|Exclusive|特別版|Deluxe|豪華"),
    ("彩膠", r"彩膠|畫膠|Colou?r|Clear|Splatter|Marble|透明|Picture Disc|Translucent|Galaxy|Swirl|Zoetrope|螢光|夜光|Glow"),
    ("180g", r"180\s?[gG克]|重量盤|Heavyweight"),
    ("日版", r"日本進口|日版|日壓|日本盤|国内盤|帯付|with OBI|日本原裝|Japan Import|JAPAN ORIGINAL|日本代購|日本限定"),
    ("台灣版", r"台壓|台灣版|台版|代理版|官方進口|環球官方|索尼官方|華納官方"),
    ("美版", r"美版|\bUS(?:A)? (?:version|Edition|Press)|美國進口"),
    ("歐版", r"歐版|\bEU\b|\bUK\b|歐洲進口|英國進口|德國進口"),
    ("BOX", r"\bBOX\b|BOX SET|Boxset|套裝|ボックス"),
    ("附特典", r"特典|附贈|贈品|限定贈"),
    ("二手", r"二手|中古|Used|九成新|拆封"),
    ("代購", r"代購|代訂|代買|日本代"),
]
TAG_RES = [(n, re.compile(p, re.I)) for n, p in TAG_RULES]


def detect_tags(title: str) -> list[str]:
    return [n for n, r in TAG_RES if r.search(title)]


# ---------------------------------------------------------------- 相關性 / 日系
ANY_MEDIA_RE = re.compile("|".join(p.pattern for p in (VINYL_RE, SEVEN_RE, CD_RE, CASSETTE_STRONG_RE, CASSETTE_WEAK_RE)), re.I)
EXCLUDE_RE = re.compile(
    r"唱盤|唱機|唱頭|唱針|唱臂|轉盤|留聲機|喇叭|音箱|擴大機|藍牙|收納|清潔|防塵|除塵|唱片刷|"
    r"唱片架|唱片櫃|展示架|保護套|內袋|外袋|內襯|釣魚|傘|雨衣|手套|地板|膠帶|壁貼|貼紙|"
    r"地墊|轉盤墊|保護膜|鞋|褲|外套|T恤|帽|包包|書包|手錶|杯|鍋|椅|桌|燈|窗簾|擺件|"
    r"裝飾畫|掛畫|時鐘|相框|公仔|PVC|BANPRESTO|一番賞|扭蛋|模型|樂譜|鋼琴譜|吉他譜|"
    r"杯墊|滑鼠墊|手機殼|徽章|吊飾|鑰匙圈|海報$|空盒|詢價|仿|非黑膠|"
    r"唱片鎮|唱片夾|紙鎮|書籤|明信片|帳篷|帳蓬|野餐|鋼琴獨奏|樂譜集|黑膠CD|刻盤|Clear File|資料夾|"
    r"\bcards?\b|卡牌|(?<![\d/])\d{2,3}/\d{2,3}(?![\d/])|Lightly Played|創意遊戲|居家擺設|玩具|"
    r"\bHolo\b|\bRare\b|Japanese LP|\bPSA\b|No\.\s?\d{3}\b|"
    r"權力遊戲|冰與火之歌|Game of Thrones|Molly.s Game|"
    r"CD機|CD播放|CD Player|隨身聽|Walkman|錄音機|卡帶機|空白卡帶|空白光碟|CD盒|CD架|CD收納|光碟機|"
    r"DVD(?!.*(?:CD|LP))|藍光(?!.*(?:CD|LP))|電子書|點讀|有聲書|兒童英語|英文繪本|"
    r"遊戲片|遊戲卡|主機|手把|Switch\s?(?:主機|遊戲)|PS[45]\s?(?:主機|遊戲)|中文版(?!.*(?:原聲|LP|黑膠))",
    re.I)
# 相關性判斷用：「遊戲」是常見中文詞（一場遊戲一場夢），需搭配音樂字眼
ACG_STRONG_RE = re.compile(
    ANIME_RE.pattern + "|" + GAME_RE.pattern.replace("遊戲|", "遊戲(?:原聲|音樂|配樂|主題|歌曲|原創|精選)|", 1)
    + r"|聲優|ボカロ|VOCALOID|久石讓|久石譲|Hisaishi", re.I)
KANA_RE = re.compile(r"[぀-ヿ]")

JP_WORK_RE = re.compile(
    r"日本|日版|日壓|[぀-ヿ]|任天堂|Nintendo|SQUARE ENIX|Square Enix|CAPCOM|Capcom|SEGA|"
    r"ATLUS|KONAMI|Konami|BANDAI|萬代|Falcom|吉卜力|Ghibli|久石讓|久石譲|Hisaishi|宮崎駿|"
    r"太空戰士|東映|Aniplex|Lantis|Toho|東寶|Dragon Ball|Tekken|鐵拳|Godzilla|哥吉拉|My Hero|"
    r"我的英雄學院|Zelda|Pokemon|Pokémon|Persona|Yakuza|人中之龍|Silent Hill|沉默之丘|"
    r"逆轉裁判|Ace Attorney|天氣之子|鈴芽|Kajiura|Kanno|Uematsu|Shimomura|Sakimoto|"
    r"崎元仁|Mitsuda|Meguro|Sawano|澤野弘之|Ryuichi Sakamoto|坂本龍一|Anime Limited|Milan Records", re.I)
WESTERN_RE = re.compile(
    r"Disney|迪士尼|Pixar|皮克斯|DreamWorks|夢工廠|Marvel|漫威|Minions|小小兵|神偷奶爸|Frozen|冰雪奇緣|"
    r"Moana|海洋奇緣|Arcane|奧術|Grinch|鬼靈精|Seuss|Hasbro|Transformers|變形金剛|Cyberpunk|電馭叛客|"
    r"KPOP|獵魔女團|Simpsons|辛普森|Shrek|史瑞克|Spider-Verse|蜘蛛人|Looney|Hanna-Barbera|"
    r"Nightmare Before|聖誕夜驚魂|Trolls|魔髮精靈|Peanuts|史努比|Snoopy|Fantastic Beasts|Harry Potter|"
    r"哈利波特|Star Wars|星際大戰|Minecraft|Hollow Knight|Stray|Syberia|Last of Us|最後生還者|"
    r"小熊維尼|Winnie the Pooh|玩具總動員|Toy Story|獅子王|Lion King|小美人魚|Little Mermaid|星際寶貝|Lilo|"
    r"可可夜總會|Coco|腦筋急轉彎|Inside Out|查理布朗|Charlie Brown|芝麻街|Sesame|海綿寶寶|SpongeBob|"
    r"Grand Theft Auto|俠盜獵車|Witcher|巫師|Fallout|異塵餘生|Halo|Doom|Diablo|暗黑破壞神|Assassin|刺客教條|"
    r"League of Legends|英雄聯盟|Overwatch|鬥陣特攻|Undertale|Hades|Celeste|Cuphead|茶杯頭|Stardew", re.I)


@dataclass
class Franchises:
    names: dict[str, re.Pattern]
    kinds: dict[str, str]

    @classmethod
    def from_config(cls, cfg: dict) -> "Franchises":
        names, kinds = {}, {}
        for name, d in cfg.get("franchises", {}).items():
            aliases = [a for a in d.get("aliases", []) if a.strip()]
            pat = "|".join(re.escape(a) if not re.match(r"^[A-Za-z0-9 .'-]+$", a)
                           else r"(?<![A-Za-z])" + re.escape(a) + r"(?![A-Za-z])" for a in aliases)
            names[name] = re.compile(pat, re.I)
            kinds[name] = d.get("kind", "anime")
        return cls(names, kinds)

    def match(self, text: str) -> str | None:
        for name, r in self.names.items():
            if r.search(text):
                return name
        return None


def is_relevant(title: str, extra: str, fr: Franchises, *, is_ost: bool = False, fmt_hint: str | None = None) -> bool:
    """title = 品名；extra = 商品描述（只當輔助證據）；is_ost = 通路分類就是原聲帶。"""
    if EXCLUDE_RE.search(title):
        return False
    if not (ANY_MEDIA_RE.search(title) or fmt_hint):
        return False
    if not detect_format(title, fmt_hint):
        return False  # 例如遊戲卡匣「卡帶」
    title = re.sub(r"動態?動畫膠", "", title)  # 「動畫膠」是畫面會動的唱片，不是動畫作品
    if ACG_STRONG_RE.search(title) or fr.match(title):
        return True
    weak_title = bool(OST_RE.search(title))
    kana = bool(KANA_RE.search(title))
    if weak_title and kana:
        return True
    # 通路分類「原聲帶」只是輔助：還需要描述裡出現動畫 / 遊戲 / 追蹤作品
    extra_acg = bool(extra and (ACG_STRONG_RE.search(extra) or fr.match(extra)))
    return (weak_title or is_ost or kana) and extra_acg


def is_japanese(text: str, franchise: str | None) -> bool:
    if franchise:
        return True
    if WESTERN_RE.search(text):
        return False
    return bool(JP_WORK_RE.search(text) or ANIME_RE.search(text))


def is_western(text: str) -> bool:
    return bool(WESTERN_RE.search(text))
