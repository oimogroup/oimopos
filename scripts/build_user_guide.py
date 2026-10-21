"""Build static, searchable and printable documentation from reviewed source JSON."""
from html import escape as e
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT/'docs/user-guide'
ROLE = {'owner':'Владелец','manager':'Руководитель','cashier':'Кассир','cook':'Кухня'}


def main():
    sections = json.loads((GUIDE/'content.json').read_text())
    scenes = {s['id']:s for s in json.loads((ROOT/'scripts/user-guide-scenes.json').read_text())}
    used = set()
    nav, articles, group = [], [], None
    for number, section in enumerate(sections, 1):
        if section['group'] != group:
            group = section['group']
            nav.append('<h2>'+e(group)+'</h2>')
        nav.append(f'<a href="#{e(section["id"])}">{e(section["title"])}</a>')
        image = ''
        if section.get('image'):
            scene = scenes[section['image']]; used.add(scene['id'])
            source = 'screenshots/'+scene['id']+'.png'
            if not (GUIDE/source).exists(): raise ValueError('Missing screenshot '+source)
            markers = ''.join(f'<li><b>{i+1}</b>{e(m["text"])}</li>' for i,m in enumerate(scene['markers']))
            image = f'<figure><button type="button" data-zoom aria-label="Увеличить: {e(scene["title"])}"><img loading="lazy" width="1440" height="1000" src="{source}" alt="{e(scene["title"])} — демонстрационный экран Oimo" /></button><figcaption>Скриншот: {e(scene["title"])}. Демонстрационные данные. Нажмите для увеличения.</figcaption><ul class="markers">{markers}</ul></figure>'
        roles = ' · '.join(ROLE[r] for r in section['roles'])
        steps = ''.join('<li>'+e(s)+'</li>' for s in section['steps'])
        note = '<p class="note">'+e(section['note'])+'</p>' if section.get('note') else ''
        articles.append(f'<article class="guide-section" id="{e(section["id"])}" data-roles="{e(",".join(section["roles"]))}"><div class="section-meta"><span class="section-number">{number:02}</span><span>{e(section["group"])} · {e(roles)}</span></div><h2>{e(section["title"])}</h2><p class="path">{e(section["path"])}</p><p class="goal">{e(section["goal"])}</p><ol class="steps">{steps}</ol><div class="result"><strong>Результат. </strong>{e(section["result"])}</div>{note}{image}</article>')
    html = '''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="Полное руководство Oimo: настройка, поставки, склад, касса, зарплаты и P&L. Пошаговые инструкции со скриншотами."><title>Oimo — руководство пользователя</title><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="guide.css?v=1"></head><body><a class="skip" href="#main">К руководству</a><header class="top"><a class="brand" href="#top"><i>o</i>Oimo<small>Руководство пользователя · 22.10.2026</small></a><div class="tools"><a href="/admin">Кабинет</a><a href="/pos">Касса</a><a href="Oimo-user-guide.pdf" download>Скачать PDF</a><button type="button" id="printGuide">Печать</button></div></header><div class="layout"><nav class="contents" aria-label="Содержание">NAV</nav><main id="main"><section class="hero" id="top"><span class="eyebrow">От первой настройки до чистой прибыли</span><h1>Как работать<br>в Oimo</h1><p>Понятные инструкции для владельца, руководителя, кассира и кухни. Куда перейти, что заполнить и как проверить результат.</p><div class="stats"><span><strong>COUNT</strong><small>инструкции</small></span><span><strong>SHOTS</strong><small>скриншотов</small></span><span><strong>4</strong><small>роли</small></span></div><div class="print-info">Версия: 22 октября 2026 года<br>Скриншоты: текущий интерфейс, демонстрационные данные<br>Содержание: настройка, меню, закупки, склад, производство, продажи, зарплата, финансы и контроль.<br>Электронная версия: /docs/user-guide/</div></section><section class="search-panel" aria-label="Поиск по руководству"><label for="guideSearch">Найдите действие или вопрос · клавиша /</label><input id="guideSearch" type="search" placeholder="Например: аренда, возврат чека, PIN, зарплата" autocomplete="off"><div class="roles" role="group" aria-label="Фильтр по роли"><button type="button" data-role-filter="all" aria-pressed="true">Все разделы</button><button type="button" data-role-filter="owner" aria-pressed="false">Владелец</button><button type="button" data-role-filter="manager" aria-pressed="false">Руководитель</button><button type="button" data-role-filter="cashier" aria-pressed="false">Кассир</button><button type="button" data-role-filter="cook" aria-pressed="false">Кухня</button></div><p id="searchCount" role="status" aria-live="polite"></p></section><div class="quicklinks"><a href="#owner-day"><strong>Я владелец</strong><small>Настроить и контролировать бизнес →</small></a><a href="#cashier-day"><strong>Я кассир</strong><small>Открыть смену и продавать →</small></a><a href="#cook-day"><strong>Я на кухне</strong><small>Приготовить и передать блюда →</small></a></div><p class="empty" id="noResults" hidden>Ничего не найдено. Попробуйте другое слово или выберите «Все разделы».</p>ARTICLES<footer class="guide-footer">Oimo · Руководство пользователя · 22 октября 2026 года<br>Примеры не изменяют вашу базу. Обновляйте руководство при изменении интерфейса и правил учёта.</footer></main></div><dialog id="imageDialog"><header><p id="zoomCaption"></p><button type="button" id="closeImage" aria-label="Закрыть изображение">Закрыть ×</button></header><img id="zoomImage" alt=""></dialog><script src="guide.js?v=1"></script></body></html>'''
    toc = '<section class="print-contents"><h2>Содержание</h2><ol>'+''.join('<li><a href="#'+e(x['id'])+'">'+e(x['title'])+'</a></li>' for x in sections)+'</ol></section>'
    html = html.replace('ARTICLES', toc+'ARTICLES')
    html = html.replace('NAV',''.join(nav)).replace('ARTICLES',''.join(articles)).replace('COUNT',str(len(sections))).replace('SHOTS',str(len(used)))
    (GUIDE/'index.html').write_text(html)
    print(f'Built {len(sections)} sections, {len(used)} screenshots')


if __name__ == '__main__': main()
