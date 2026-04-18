# Universal-Compress-tool-experiment

Aplikacja desktopowa do bezstratnej kompresji i dekompresji plik?w oraz tekstu z w?asnym kontenerem `PYLC1` zapisanym jako plik `*.pylc`.
Program ma interfejs Tkinter i pozwala zar?wno testowa? r??ne algorytmy, jak i wygodnie odzyskiwa? dane z archiw?w.

## Co robi skrypt

Program pozwala na trzy g??wne scenariusze:

1. Kompresja pliku do archiwum `*.pylc`.
2. Kompresja tekstu wpisanego r?cznie lub wczytanego z pliku `.txt`.
3. Dekompresja i test integralno?ci wcze?niej utworzonego archiwum.

Podczas kompresji program:

- liczy sum? SHA-256 danych wej?ciowych,
- zapisuje metadane w nag??wku kontenera `PYLC1`,
- kompresuje dane jednym algorytmem albo testuje kilka i wybiera najmniejszy wynik,
- zapisuje wynik do pliku `*.pylc`.

Podczas dekompresji program:

- odczytuje nag??wek archiwum,
- odzyskuje oryginalny plik lub tekst,
- opcjonalnie weryfikuje SHA-256,
- opcjonalnie przywraca oryginalny znacznik czasu pliku,
- mo?e za?adowa? odzyskany tekst z powrotem do pola tekstowego w GUI.

## Obs?ugiwane algorytmy

Program korzysta z modu??w dost?pnych w aktualnym interpreterze Pythona:

- `zlib`
- `gzip`
- `bz2`
- `lzma`

Je?eli wybierzesz tryb `Minimum z wybranych`, aplikacja uruchomi kompresj? dla zaznaczonych algorytm?w i zachowa najmniejszy wynik.

## Struktura projektu

Najwa?niejsze pliki:

- `launcher.py` - g??wny plik launchera uruchamiany bezpo?rednio przez u?ytkownika.
- `Code/__main__.py` - alternatywny start modu?owy, korzystaj?cy z tego samego bootstrapu.
- `Code/runtime_bootstrap.py` - sprawdzanie `requirements.txt` i instalacja brakuj?cych pakiet?w po zgodzie u?ytkownika.
- `Code/pylossless/main.py` - uruchomienie programu i instalacja globalnych hook?w wyj?tk?w.
- `Code/pylossless/gui.py` - interfejs u?ytkownika Tkinter.
- `Code/pylossless/jobs.py` - kompresja, dekompresja, estymacja rozmiaru i test integralno?ci.
- `Code/pylossless/container.py` - zapis i odczyt nag??wka formatu `PYLC1`.
- `Code/pylossless/error_logging.py` - globalny catcher wyj?tk?w i zapis raport?w b??d?w do `.txt`.
- `requirements.txt` - lista zewn?trznych pakiet?w instalowanych przez `pip`.
- `tests/` - testy jednostkowe logiki bez GUI.

## Wymagania i zale?no?ci

Aktualna wersja projektu dzia?a wy??cznie na bibliotece standardowej Pythona, wi?c `requirements.txt` jest obecnie pusty z premedytacj?.
Plik zosta? jednak dodany ju? teraz, ?eby projekt by? przygotowany na przysz?e rozszerzenia wymagaj?ce pakiet?w zewn?trznych.

Launcher przy starcie dzia?a bez GUI i przez konsol?:

- sprawdza zawarto?? `requirements.txt`,
- wykrywa brakuj?ce pakiety,
- wypisuje ich list? w konsoli,
- pyta u?ytkownika o zgod? na instalacj?,
- dopiero po potwierdzeniu uruchamia `pip install -r requirements.txt`,
- po poprawnym sprawdzeniu lub instalacji uruchamia w?a?ciwe GUI aplikacji.

Je?li u?ytkownik odm?wi, launcher zatrzyma start i poka?e w konsoli polecenie do r?cznej instalacji.
Je?eli instalacja przez `pip` si? nie powiedzie, szczeg??y trafiaj? do pliku `.txt` w katalogu log?w aplikacji.

R?czna instalacja zale?no?ci:

```bash
python -m pip install -r requirements.txt
```

## Jak uruchomi?

Uruchamiaj projekt przez plik `launcher.py`.
To on najpierw sprawdza zale?no?ci w konsoli, a dopiero potem startuje GUI.

Je?li chcesz uruchamia? go z terminala, mo?esz u?y?:

```bash
python launcher.py
```

Po starcie zobaczysz okno z trzema zak?adkami:

- `Kodowanie pliku`
- `Kodowanie tekstu`
- `Dekodowanie`

## Jak u?ywa? programu

### 1. Kompresja pliku

1. Wejd? w zak?adk? `Kodowanie pliku`.
2. Wybierz plik wej?ciowy.
3. Po prawej ustaw algorytm, poziom kompresji i pozosta?e opcje.
4. Kliknij `Oszacuj rozmiar`, je?li chcesz najpierw zobaczy? przybli?ony wynik.
5. Kliknij `Koduj plik`.

Efekt:

- program utworzy archiwum `*.pylc`,
- domy?lnie zapisze je obok pliku wej?ciowego, chyba ?e wska?esz katalog wyj?ciowy,
- w dzienniku poka?e przebieg i wybrany algorytm.

### 2. Kompresja tekstu

1. Wejd? w zak?adk? `Kodowanie tekstu`.
2. Wpisz tekst r?cznie albo kliknij `Wczytaj TXT...`.
3. Ustaw nazw? przysz?ego pliku tekstowego, pod jak? dane b?d? zapisane w metadanych.
4. Opcjonalnie u?yj `Oszacuj rozmiar`.
5. Kliknij `Koduj tekst`.

Efekt:

- tekst zostanie zapisany do archiwum `*.pylc`,
- przy dekompresji mo?e zosta? odzyskany jako plik i opcjonalnie zaczytany z powrotem do pola tekstowego.

### 3. Dekompresja archiwum

1. Wejd? w zak?adk? `Dekodowanie`.
2. Wybierz plik `*.pylc`.
3. Opcjonalnie kliknij `Czytaj nag??wek`, aby podejrze? metadane.
4. Kliknij `Dekoduj`.

Efekt:

- program odzyska dane do wskazanego katalogu,
- je?li zaznaczona jest opcja przywracania oryginalnej lokalizacji i katalog istnieje, spr?buje zapisa? plik w?a?nie tam,
- je?li archiwum pochodzi?o z tekstu, mo?e dodatkowo za?adowa? tekst do zak?adki tekstowej.

### 4. Test integralno?ci

1. W zak?adce `Dekodowanie` wybierz archiwum `*.pylc`.
2. Kliknij `Test integralno?ci`.

Program sprawdzi, czy:

- strumie? da si? poprawnie zdekodowa?,
- liczba odzyskanych bajt?w zgadza si? z nag??wkiem,
- suma SHA-256 zgadza si? z warto?ci? zapisan? w archiwum, je?li by?a wymagana.

## Najwa?niejsze opcje w GUI

- `Jeden algorytm` - kompresja wy??cznie wybranym algorytmem.
- `Minimum z wybranych` - test kilku algorytm?w i wyb?r najmniejszego wyniku.
- `Nadpisuj istniej?ce pliki` - zapis bez tworzenia kolejnych wariant?w z sufiksem.
- `Weryfikuj SHA-256 przy dekodowaniu` - kontrola integralno?ci odzyskiwanych danych.
- `Przywracaj znacznik czasu pliku po dekodowaniu` - pr?ba odtworzenia `mtime` orygina?u.
- `Przywracaj do oryginalnej lokalizacji, je?li istnieje` - u?ycie ?cie?ki zapisanej w nag??wku archiwum.
- `Otw?rz folder po zako?czeniu` - szybkie przej?cie do katalogu wyniku po zako?czonej operacji.

## Gdzie program zapisuje pliki

### Ustawienia

Plik ustawie? jest zapisywany w katalogu u?ytkownika:

- Windows: `%APPDATA%\PyLossless Studio\pylossless_settings.json`
- Linux: `~/.config/PyLossless Studio/pylossless_settings.json`
- macOS: `~/Library/Application Support/PyLossless Studio/pylossless_settings.json`

### Domy?lne katalogi wynik?w

Je?li nie wska?esz w?asnej lokalizacji, program u?ywa katalog?w u?ytkownika aplikacji:

- `wynik_zakodowany`
- `wynik_odkodowany`

### Logi b??d?w

W razie b??du program zapisuje raporty `.txt` w katalogu:

- Windows: `%APPDATA%\PyLossless Studio\logs`
- Linux: `~/.config/PyLossless Studio/logs`
- macOS: `~/Library/Application Support/PyLossless Studio/logs`

Raport b??du zawiera mi?dzy innymi:

- dat? i godzin?,
- wersj? aplikacji,
- komunikat b??du,
- traceback,
- kontekst operacji.

## Obs?uga b??d?w

Program ma teraz trzy poziomy obs?ugi problem?w:

- b??dy zada? roboczych podczas kompresji, dekompresji albo testu integralno?ci,
- globalne, nieobs?u?one wyj?tki z g??wnego w?tku, w?tk?w Pythona i callback?w Tkinter,
- b??dy bootstrapu zale?no?ci, czyli brak pakiet?w z `requirements.txt` albo nieudana instalacja przez `pip`.

Je?li co? p?jdzie nie tak, u?ytkownik dostaje komunikat w GUI, a szczeg??owy raport trafia do pliku `.txt`.

## Testy

Uruchomienie test?w:

```bash
python -m unittest discover -s tests -v
```

Aktualne testy sprawdzaj? mi?dzy innymi:

- poprawny round-trip tekstu,
- zachowanie dekompresji przy b??dnym kodowaniu tekstu w nag??wku,
- wykrywanie niezgodno?ci rozmiaru w te?cie integralno?ci,
- tworzenie raport?w b??d?w `.txt`,
- odczyt `requirements.txt` i logik? bootstrapu zale?no?ci.

## Porz?dki w plikach

W projekcie zosta?y usuni?te zb?dne pliki pomocnicze, kt?re dublowa?y aktualn? logik? lub nie by?y ju? u?ywane:

- `Code/code.py` - zast?piony przez jeden launcher `launcher.py`,
- `Code/pylossless/settings.py` - nieu?ywany po przeniesieniu obs?ugi ustawie? do GUI.
