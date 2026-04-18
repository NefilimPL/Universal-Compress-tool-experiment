# Universal-Compress-tool-experiment

Projekt zosta? przebudowany z jednego du?ego pliku do modu?owej struktury w `Code/pylossless/`.
GUI zosta?o zostawione, ale logika kompresji, nag??wk?w, ustawie? i zada? roboczych jest teraz
wydzielona i testowalna.

Najwa?niejsze katalogi:

- `Code/code.py` uruchamia aplikacj?.
- `Code/pylossless/algorithms.py` trzyma rejestr algorytm?w i adaptery kompresji.
- `Code/pylossless/container.py` obs?uguje format kontenera `PYLC1`.
- `Code/pylossless/jobs.py` zawiera kompresj?, dekompresj?, weryfikacj? i estymacj?.
- `Code/pylossless/gui.py` zawiera tylko warstw? Tkinter.
- `tests/test_jobs.py` sprawdza logik? bez GUI.

Poprawki wzgl?dem poprzedniej wersji:

- dekodowanie nie gubi ju? odzyskanego pliku, gdy automatyczne wczytanie tekstu do pola si? nie powiedzie,
- test integralno?ci wykrywa te? niezgodno?? rozmiaru po dekompresji,
- ustawienia s? zapisywane w katalogu u?ytkownika zamiast obok skryptu,
- kod jest rozdzielony na nazwane modu?y, dzi?ki czemu ?atwiej go rozwija?.

Za?o?enia z PDF-a zosta?y potraktowane jako kierunek architektury:

- zachowujemy prawdziwie bezstratne odtwarzanie danych wej?ciowych,
- logika kompresji jest odseparowana od GUI, wi?c ?atwo doda? kolejne kodeki lub tryby eksperymentalne,
- projekt jest gotowy pod dalsze rozszerzenia zwi?zane z kr?tkimi polskimi frazami, Unicode i niskim narzutem.

Uruchomienie:

```bash
python Code/code.py
```

Testy:

```bash
python -m unittest discover -s tests
```
