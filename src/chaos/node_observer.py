"""Read-only observations for verified exploration nodes; unknown screens fail closed."""

import json
from pathlib import Path

import cv2
import numpy as np

from src.image_matcher import read_image


class NodeObserver:
    def __init__(self, root, ocr=None):
        root = Path(root)
        self.config = json.loads((root / 'src/chaos/node_layout.json').read_text(encoding='utf-8'))
        self.templates = {}
        for name, definition in self.config['markers'].items():
            source = read_image(str(root / definition['file']))
            if source is None:
                raise ValueError(f'노드 이미지 누락: {definition["file"]}')
            if 'crop' in definition:
                x, y, w, h = definition['crop']
                source = source[y:y+h, x:x+w]
                if source.shape[:2] != (h, w):
                    raise ValueError(f'노드 이미지 영역 오류: {name}')
            self.templates[name] = source.copy()
        self.blocked = []
        for path in sorted((root / 'images/chaos/node_progression/templates/blocked_choices').glob('*.png')):
            source = read_image(str(path))
            if source is None:
                raise ValueError(f'금지 이미지 읽기 실패: {path}')
            self.blocked.append((path.stem, source))
        if not self.blocked:
            raise ValueError('금지 이미지 목록이 비어 있습니다.')
        self.ocr = ocr

    def validate_screen(self, screen):
        if screen is None or screen.shape[:2] != (720, 1280):
            raise RuntimeError('새 1280×720 화면을 읽지 못했습니다.')

    @staticmethod
    def matches(screen, template, region, threshold=.9, max_error=.055):
        x, y, w, h = region
        th, tw = template.shape[:2]
        if x < 0 or y < 0 or x+w > screen.shape[1] or y+h > screen.shape[0] or w < tw or h < th:
            return []
        sample = screen[y:y+h, x:x+w]
        scores = cv2.matchTemplate(sample, template, cv2.TM_CCOEFF_NORMED)
        found = []
        for _ in range(100):
            _, score, _, (mx, my) = cv2.minMaxLoc(scores)
            if score < threshold:
                break
            error = np.abs(sample[my:my+th, mx:mx+tw].astype(float)-template).mean()/255
            if error <= max_error:
                found.append((x+mx, y+my, tw, th))
            scores[max(0,my-th//2):my+th//2+1, max(0,mx-tw//2):mx+tw//2+1] = -1
        return found

    def all(self, screen, name, region=None):
        d = self.config['markers'][name]
        return self.matches(screen, self.templates[name], region or d.get('region', [0,0,1280,720]), d['threshold'], d['max_color_error'])

    def find(self, screen, name, region=None):
        matches = self.all(screen, name, region)
        return matches[0] if len(matches) == 1 else None

    def forbidden(self, screen):
        found = []
        for name, template in self.blocked:
            for scale in (1., .85, .9, .8, 1.1):
                scaled = template if scale == 1 else cv2.resize(template, None, fx=scale, fy=scale)
                for bounds in self.matches(screen, scaled, [0,0,1280,720], .88, .18):
                    x,y,w,h = bounds
                    if not any(old_name == name and abs(ox+ow/2-x-w/2)<max(w,ow)/2
                               and abs(oy+oh/2-y-h/2)<max(h,oh)/2 for old_name,(ox,oy,ow,oh) in found):
                        found.append((name,bounds))
        return found

    def arrows(self, screen):
        arrows = self.all(screen, 'arrow')
        for bounds in self.all(screen, 'arrow_boss'):
            if not any(abs(bounds[0]-old[0])<15 and abs(bounds[1]-old[1])<15 for old in arrows):
                arrows.append(bounds)
        return arrows

    def candidates(self, screen):
        arrows = self.arrows(screen)
        candidates = []
        for name in self.config['priority'] + ['boss']:
            for b in self.all(screen, 'node_'+name):
                x,y,w,h = b
                if any(abs(ax+aw/2-x-w/2)<22 and 0<y-ay<45 for ax,ay,aw,ah in arrows):
                    candidates.append((name, b))
        # Every reachable marker must resolve to exactly one type, otherwise stop.
        if any(sum(abs(ax+aw/2-b[0]-b[2]/2)<22 and 0<b[1]-ay<45 for _,b in candidates) != 1
               for ax,ay,aw,ah in arrows):
            raise RuntimeError('진입 가능 표시와 노드 종류를 명확히 연결하지 못했습니다.')
        return candidates

    def choose_node(self, screen):
        blocked = self.forbidden(screen)
        candidates = self.candidates(screen)
        # Blocks inside a node remove that candidate; unassociated blocks stop.
        for _, (bx,by,bw,bh) in blocked:
            linked = [c for c in candidates if c[1][0]-25 <= bx+bw/2 <= c[1][0]+c[1][2]+25
                      and c[1][1]-25 <= by+bh/2 <= c[1][1]+c[1][3]+25]
            if not linked:
                raise RuntimeError('금지 항목이 있는 선택 화면입니다. 대응 규칙 확인이 필요합니다.')
            candidates = [c for c in candidates if c not in linked]
        if not candidates:
            raise RuntimeError('선택 가능한 노드가 없습니다.')
        order = self.config['priority'] + ['boss']
        return min(candidates, key=lambda c:(order.index(c[0]), c[1][1], c[1][0]))

    def loot_choices(self, screen):
        """Apply global forbidden scan before choosing any verified loot card."""
        forbidden = self.forbidden(screen)
        cards = [tuple(b) for b in self.config['loot_cards']]
        anchors = sorted(self.all(screen, 'loot_reroll'))
        if len(anchors) != len(cards) or any(not (cx <= x+w/2 <= cx+cw and cy+ch <= y <= cy+ch+60)
                for (x,y,w,h),(cx,cy,cw,ch) in zip(anchors,cards)):
            raise RuntimeError('전리품 카드 배치를 확인하지 못했습니다.')
        blocked = set()
        for name, (x,y,w,h) in forbidden:
            owners = [i for i,(cx,cy,cw,ch) in enumerate(cards)
                      if cx <= x+w/2 <= cx+cw and cy <= y+h/2 <= cy+ch]
            if len(owners) != 1:
                raise RuntimeError('금지 이미지가 속한 전리품 카드를 확정하지 못했습니다.')
            blocked.add(owners[0])
        return [b for i,b in enumerate(cards) if i not in blocked]

    def selected_loot(self, screen):
        edges = self.all(screen, 'loot_selected_edge')
        if len(edges) != 1: return None
        x,y,w,h=edges[0]
        cards=[tuple(b) for b in self.config['loot_cards'] if abs(b[0]-x)<22]
        return cards[0] if len(cards)==1 else None

    def classify(self, screen):
        if self.find(screen, 'defeat'): return 'defeat'
        if self.find(screen, 'expedition_summary') and self.find(screen, 'summary_close'): return 'expedition_summary'
        if self.find(screen, 'exploration_entry'): return 'exploration_entry'
        if self.find(screen, 'shop_exit_dialog') and self.find(screen, 'story_confirm'): return 'shop_exit_confirm'
        if self.find(screen, 'unclaimed_dialog'): return 'unclaimed_reward'
        if self.find(screen, 'recruit_reward_title') and self.find(screen, 'recruit_continue'): return 'recruit_reward'
        if self.find(screen, 'story_dialog'): return 'story_confirm'
        if self.find(screen, 'levelup') and self.find(screen, 'level_close'): return 'levelup'
        if self.find(screen, 'rank_close'): return 'rank_result'
        if self.find(screen, 'event_loot_close'): return 'event_loot_popup'
        if self.event_result_marker(screen) and self.find(screen, 'event_advance'): return 'event_result'
        if any(self.find(screen, e['state_marker']) for e in self.config.get('events', [])): return 'event'
        if len(self.all(screen,'loot_reroll')) == 3 and (self.find(screen,'loot_button') or self.find(screen,'loot_button_dim')): return 'loot'
        if self.find(screen, 'victory') and self.find(screen, 'continue'): return 'victory'
        if self.find(screen,'shop_frame') and self.find(screen,'shop_exit'): return 'shop'
        if self.find(screen,'leave') and (self.find(screen,'supply_loot') or self.find(screen,'supply_done')): return 'supply'
        if self.find(screen, 'rank_title'): return 'rank_menu'
        if self.find(screen, 'leave') and (self.find(screen, 'detail_rest') or self.find(screen, 'rest_done')): return 'rest'
        if self.find(screen, 'battle_start'): return 'battle_setup'
        if self.find(screen, 'enter_node') and self.find(screen, 'detail_battle'): return 'battle_detail'
        if self.find(screen, 'enter_node') and self.find(screen, 'rest_detail'): return 'rest_detail'
        if self.find(screen, 'enter_node') and self.find(screen, 'supply_detail'): return 'supply_detail'
        if self.find(screen, 'enter_node') and self.find(screen, 'elite_detail'): return 'elite_detail'
        if self.find(screen, 'enter_node') and self.find(screen, 'boss_detail'): return 'boss_detail'
        if self.find(screen, 'enter_node') and self.find(screen, 'event_detail'): return 'event_detail'
        if self.find(screen, 'enter_node'): return 'node_detail'
        if self.find(screen, 'map_footer') and self.arrows(screen): return 'map'
        if self.find(screen, 'battle_ui'): return 'battle'
        if self.find(screen, 'skip'): return 'story'
        return None

    def event_result_marker(self, screen):
        names = self.config.get('event_result_markers', []) + [e['result_marker'] for e in self.config.get('events', []) if e.get('result_marker')]
        found = [name for name in names if self.find(screen, name)]
        return found[0] if len(found) == 1 else None

    def event_choice(self, screen):
        # Only reviewed outcomes are allowed; absence of a forbidden image alone
        # does not establish that an unknown event preserves the party.
        blocked = self.forbidden(screen)
        events = [e for e in self.config.get('events', []) if self.find(screen, e['state_marker'])]
        if len(events) != 1: return None
        event = events[0]
        priority = self.config['event_effect_priority']
        candidates = [c for c in event['choices'] if c['effect'] in priority and self.find(screen, c['choice_marker'])]
        if not candidates: return None
        for _,(bx,by,bw,bh) in blocked:
            owners = [r for r in event['choice_regions'] if r[0] <= bx+bw/2 <= r[0]+r[2]
                      and r[1] <= by+bh/2 <= r[1]+r[3]]
            if len(owners) != 1: raise RuntimeError('이벤트 금지 이미지의 선택지 연결 확인이 필요합니다.')
            candidates = [c for c in candidates if c['bounds'] != owners[0]]
        if not candidates: raise RuntimeError('금지 항목 제외 후 허용 이벤트 선택지가 없습니다.')
        choice = min(candidates, key=lambda c: priority.index(c['effect']))
        return tuple(choice['bounds'])

    def known_event(self, screen):
        found = [e['id'] for e in self.config['events'] if self.find(screen,e['state_marker'])]
        return found[0] if len(found) == 1 else None

    def event_cards(self, screen):
        # Bottom corners remain visible when a magnifier replaces the top icon.
        left = sorted((x,y-100,w,h) for x,y,w,h in self.all(screen,'event_card_left'))
        right = sorted(self.all(screen,'event_card_right'))
        if len(left) not in (2,3) or len(right) != len(left): return []
        cards = []
        for (x,y,_,_),(rx,ry,_,_) in zip(left,right):
            if abs(y-ry)>3 or not 330 <= rx-x <= 345: return []
            cards.append((x+5,y+4,362,131))
        if max(c[1] for c in cards)-min(c[1] for c in cards)>3: return []
        if any(a[0]+a[2] >= b[0] for a,b in zip(cards,cards[1:])): return []
        return cards

    def available_event_cards(self, screen, cards):
        blocked = self.forbidden(screen)
        available = []
        excluded = set()
        for _,(x,y,w,h) in blocked:
            owners = [i for i,(cx,cy,cw,ch) in enumerate(cards)
                      if cx <= x+w/2 <= cx+cw and cy <= y+h/2 <= cy+ch]
            if len(owners) != 1: raise RuntimeError('금지 이미지가 속한 이벤트 선택지를 확인하지 못했습니다.')
            excluded.add(owners[0])
        for i,(x,y,w,h) in enumerate(cards):
            interior = cv2.cvtColor(screen[y+22:y+h-12,x+15:x+w-15],cv2.COLOR_BGR2GRAY)
            if i not in excluded and np.percentile(interior,99) >= 170:
                available.append((x,y,w,h))
        return available

    def rank(self, screen, name):
        bounds = self.find(screen, name)
        if not bounds: return None
        x,y,_,_ = bounds
        return self.read_rank_digit(screen[y+35:y+61, x-16:x+1])

    def read_rank_digit(self, sample):
        if self.ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            self.ocr = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
        rows, _ = self.ocr(cv2.resize(sample, None, fx=4, fy=4), use_det=False, use_cls=False)
        if not rows or len(rows) != 1: return None
        text, confidence = rows[0]
        return int(text) if text in ('1','2','3','4','5') and confidence >= .95 else None

    @staticmethod
    def progress_signature(screen):
        # Turn portraits and acting hero label; exclude animated battlefield and skills.
        return np.concatenate([screen[115:490, 0:72].flatten(), screen[628:663, 205:485].flatten()]).astype(float)
