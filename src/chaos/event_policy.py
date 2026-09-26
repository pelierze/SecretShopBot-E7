"""Local, on-demand policies for unregistered two/three-choice events."""

import re
from pathlib import Path

import cv2

def interpret_effect(title, effect):
    """Allow complete known effect expressions, never absence of harmful words."""
    clean = lambda s: re.sub(r'[^가-힣0-9%]', '', s)
    title, effect = clean(title), clean(effect)
    text = title + effect
    if re.search(r'이탈|희생|사망|전투불능|생명력.*감소|체력.*감소|잃는다|제거|소멸', text):
        return None
    cost_match = re.search(r'차원의파편(\d+)소모', effect)
    cost = int(cost_match[1]) if cost_match else 0
    remaining = re.sub(r'차원의파편\d+소모', '', effect)
    if re.fullmatch(r'(?:(?:\d+%확률로)?(?:선택한|무작위)?영웅(?:의)?(?:1명)?랭크(?:\d+)?단계상승)', remaining):
        return ('rank_up', 0, cost)
    if re.fullmatch(r'전투후(?:차원의파편\d+획득|무작위전리품\d+개획득)', remaining):
        return ('battle_reward', 1, cost)
    if re.fullmatch(r'(?:경험치)?\d+(?:획득)?', remaining) and re.search(r'기도|수습|유해|씨앗|풀', title):
        return ('experience', 2, cost)
    if re.fullmatch(r'차원의파편\d+획득', remaining) or (re.fullmatch(r'\d+', remaining) and re.search(r'연료|보충', title)):
        return ('currency_reward', 2, cost)
    if re.fullmatch(r'(?:(?:모든|무작위|선택한)?영웅(?:의)?(?:1명)?)?(?:생명력|체력)\d+%?회복', remaining):
        return ('heal', 2, cost)
    if not remaining and re.search(r'우회한다|떠난다|지나친다|돌아간다|나간다|멈춘다|돌아선다|쉰다|물러난다', title):
        return ('leave', 3, cost)
    if re.fullmatch(r'(?:전투후)?(?:\d+%확률로)?무작위전리품\d+개획득', remaining) or re.fullmatch(r'차원주사위\d+개획득', remaining):
        return ('random_loot', 4, cost)
    if re.fullmatch(r'(?:사수|도적|마도사|전사|기사|정령사)?영웅(?:\d+명)?영입(?:권)?', remaining):
        return ('hero_recruit', 4, cost)
    return None


class KoreanEventReader:
    """Loaded only on the first unknown OCR event; no online service."""

    def __init__(self, root, engine=None):
        self.root = Path(root)
        self.engine = engine

    def _read(self, image):
        if self.engine is None:
            from rapidocr_onnxruntime import RapidOCR
            model = self.root / 'assets/ocr/korean_PP-OCRv4_rec_mobile.onnx'
            if not model.is_file():
                raise RuntimeError('한국어 이벤트 OCR 모델이 없습니다. 설치 파일을 확인해 주세요.')
            self.engine = RapidOCR(rec_model_path=str(model), intra_op_num_threads=2,
                                   inter_op_num_threads=2, det_limit_type='max', det_limit_side_len=960)
        rows, _ = self.engine(image, use_cls=False)
        return rows or []

    def choices(self, screen, cards):
        result = []
        for bounds in cards:
            x,y,w,h = bounds
            rows = self._read(screen[y+18:y+h-5, x+10:x+w-10])
            rows.sort(key=lambda row: (sum(p[1] for p in row[0])/4, row[0][0][0]))
            title, effects, scores = [], [], []
            for box,text,score in rows:
                scores.append(float(score))
                (title if sum(p[1] for p in box)/4 < 57 else effects).append(text)
            title, effect = ' '.join(title), ' '.join(effects)
            confident = bool(scores) and min(scores) >= .90
            rule = interpret_effect(title, effect) if confident else None
            result.append(dict(bounds=tuple(bounds), title=title, effect=effect,
                               confidence=min(scores) if scores else 0., rule=rule))
        return result

    def currency(self, screen):
        # Small HUD digits need enlargement; retain the full number area.
        rows = self._read(cv2.resize(screen[14:48,900:974], None, fx=3, fy=3))
        numbers = [int(t.replace(',', '')) for _,t,c in rows
                   if c >= .95 and re.fullmatch(r'\d[\d,]*', t)]
        return numbers[0] if len(numbers) == 1 else None


def choose_read_choice(rows, currency=None):
    allowed = [r for r in rows if r['rule'] and
               (not r['rule'][2] or (currency is not None and currency >= r['rule'][2]))]
    if not allowed:
        raise RuntimeError('미등록 이벤트에서 비용·효과가 확인된 허용 선택지가 없습니다.')
    return min(allowed, key=lambda r:(r['rule'][1],r['bounds'][0]))
