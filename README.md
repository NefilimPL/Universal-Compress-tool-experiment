# Universal-Compress-tool-experiment

Aplikacja desktopowa do bezstratnej kompresji i dekompresji plików oraz tekstu z własnym kontenerem `PYLC1` zapisanym jako plik `*.pylc`.
Program ma interfejs Tkinter i pozwala zarówno testować różne algorytmy, jak i wygodnie odzyskiwać dane z archiwów.

## Co robi skrypt

Program pozwala na trzy główne scenariusze:

1. Kompresja pliku do archiwum `*.pylc`.
2. Kompresja tekstu wpisanego ręcznie lub wczytanego z pliku `.txt`.
3. Dekompresja i test integralności wcześniej utworzonego archiwum.

Podczas kompresji program:

- liczy sumę SHA-256 danych wejściowych,
- zapisuje metadane w nagłówku kontenera `PYLC1`,
- kompresuje dane jednym algorytmem albo testuje kilka i wybiera najmniejszy wynik,
- zapisuje wynik do pliku `*.pylc`.

Podczas dekompresji program:

- odczytuje nagłówek archiwum,
- odzyskuje oryginalny plik lub tekst,
- opcjonalnie weryfikuje SHA-256,
- opcjonalnie przywraca oryginalny znacznik czasu pliku,
- może załadować odzyskany tekst z powrotem do pola tekstowego w GUI.

## Obsługiwane algorytmy

Program korzysta z modułów dostępnych w aktualnym interpreterze Pythona:

- `zlib`
- `gzip`
- `bz2`
- `lzma`

Jeżeli wybierzesz tryb `Minimum z wybranych`, aplikacja uruchomi kompresję dla zaznaczonych algorytmów i zachowa najmniejszy wynik.

## Struktura projektu

Najważniejsze pliki:

- `launcher.py` - główny plik launchera uruchamiany bezpośrednio przez użytkownika.
- `Code/__main__.py` - alternatywny start modułowy, korzystający z tego samego bootstrapu.
- `Code/runtime_bootstrap.py` - sprawdzanie `requirements.txt` i instalacja brakujących pakietów po zgodzie użytkownika.
- `Code/pylossless/main.py` - uruchomienie programu i instalacja globalnych hooków wyjątków.
- `Code/pylossless/gui.py` - interfejs użytkownika Tkinter.
- `Code/pylossless/jobs.py` - kompresja, dekompresja, estymacja rozmiaru i test integralności.
- `Code/pylossless/container.py` - zapis i odczyt nagłówka formatu `PYLC1`.
- `Code/pylossless/error_logging.py` - globalny catcher wyjątków i zapis raportów błędów do `.txt`.
- `requirements.txt` - lista zewnętrznych pakietów instalowanych przez `pip`.
- `tests/` - testy jednostkowe logiki bez GUI.

## Wymagania i zależności

Aktualna wersja projektu działa wyłącznie na bibliotece standardowej Pythona, więc `requirements.txt` jest obecnie pusty z premedytacją.
Plik został jednak dodany już teraz, żeby projekt był przygotowany na przyszłe rozszerzenia wymagające pakietów zewnętrznych.

Launcher przy starcie działa bez GUI i przez konsolę:

- sprawdza zawartość `requirements.txt`,
- wykrywa brakujące pakiety,
- wypisuje ich listę w konsoli,
- pyta użytkownika o zgodę na instalację,
- dopiero po potwierdzeniu uruchamia `pip install -r requirements.txt`,
- po poprawnym sprawdzeniu lub instalacji uruchamia właściwe GUI aplikacji.

Jeśli użytkownik odmówi, launcher zatrzyma start i pokaże w konsoli polecenie do ręcznej instalacji.
Jeżeli instalacja przez `pip` się nie powiedzie, szczegóły trafiają do pliku `.txt` w katalogu logów aplikacji.

Ręczna instalacja zależności:

```bash
python -m pip install -r requirements.txt
```

## Jak uruchomić

Uruchamiaj projekt przez plik `launcher.py`.
To on najpierw sprawdza zależności w konsoli, a dopiero potem startuje GUI.

Jeśli chcesz uruchamiać go z terminala, możesz użyć:

```bash
python launcher.py
```

Po starcie zobaczysz okno z trzema zakładkami:

- `Kodowanie pliku`
- `Kodowanie tekstu`
- `Dekodowanie`

## Jak używać programu

### 1. Kompresja pliku

1. Wejdź w zakładkę `Kodowanie pliku`.
2. Wybierz plik wejściowy.
3. Po prawej ustaw algorytm, poziom kompresji i pozostałe opcje.
4. Kliknij `Oszacuj rozmiar`, jeśli chcesz najpierw zobaczyć przybliżony wynik.
5. Kliknij `Koduj plik`.

Efekt:

- program utworzy archiwum `*.pylc`,
- domyślnie zapisze je obok pliku wejściowego, chyba że wskażesz katalog wyjściowy,
- w dzienniku pokaże przebieg i wybrany algorytm.

### 2. Kompresja tekstu

1. Wejdź w zakładkę `Kodowanie tekstu`.
2. Wpisz tekst ręcznie albo kliknij `Wczytaj TXT...`.
3. Ustaw nazwę przyszłego pliku tekstowego, pod jaką dane będą zapisane w metadanych.
4. Opcjonalnie użyj `Oszacuj rozmiar`.
5. Kliknij `Koduj tekst`.

Efekt:

- tekst zostanie zapisany do archiwum `*.pylc`,
- przy dekompresji może został odzyskany jako plik i opcjonalnie zaczytany z powrotem do pola tekstowego.

### 3. Dekompresja archiwum

1. Wejdź w zakładkę `Dekodowanie`.
2. Wybierz plik `*.pylc`.
3. Opcjonalnie kliknij `Czytaj nagłówek`, aby podejrzeć metadane.
4. Kliknij `Dekoduj`.

Efekt:

- program odzyska dane do wskazanego katalogu,
- jeśli zaznaczona jest opcja przywracania oryginalnej lokalizacji i katalog istnieje, spróbuje zapisać plik właśnie tam,
- jeśli archiwum pochodziło z tekstu, może dodatkowo załadować tekst do zakładki tekstowej.

### 4. Test integralności

1. W zakładce `Dekodowanie` wybierz archiwum `*.pylc`.
2. Kliknij `Test integralności`.

Program sprawdzi, czy:

- strumień da się poprawnie zdekodować,
- liczba odzyskanych bajtów zgadza się z nagłówkiem,
- suma SHA-256 zgadza się z wartością zapisaną w archiwum, jeśli była wymagana.

## Najważniejsze opcje w GUI

- `Jeden algorytm` - kompresja wyłącznie wybranym algorytmem.
- `Minimum z wybranych` - test kilku algorytmów i wybór najmniejszego wyniku.
- `Nadpisuj istniejące pliki` - zapis bez tworzenia kolejnych wariantów z sufiksem.
- `Weryfikuj SHA-256 przy dekodowaniu` - kontrola integralności odzyskiwanych danych.
- `Przywracaj znacznik czasu pliku po dekodowaniu` - próba odtworzenia `mtime` oryginału.
- `Przywracaj do oryginalnej lokalizacji, jeśli istnieje` - użycie ścieżki zapisanej w nagłówku archiwum.
- `Otwórz folder po zakończeniu` - szybkie przejście do katalogu wyniku po zakończonej operacji.
- Podpowiedzi po najechaniu kursorem - dodatkowe objaśnienia pól, przycisków i opcji bezpośrednio w GUI.

## Gdzie program zapisuje pliki

### Ustawienia

Plik ustawień jest zapisywany w katalogu użytkownika:

- Windows: `%APPDATA%\PyLossless Studio\pylossless_settings.json`
- Linux: `~/.config/PyLossless Studio/pylossless_settings.json`
- macOS: `~/Library/Application Support/PyLossless Studio/pylossless_settings.json`

### Domyślne katalogi wyników

Jeśli nie wskażesz własnej lokalizacji, program używa katalogów użytkownika aplikacji:

- `wynik_zakodowany`
- `wynik_odkodowany`

### Logi błędów

W razie błędu program zapisuje raporty `.txt` w katalogu:

- Windows: `%APPDATA%\PyLossless Studio\logs`
- Linux: `~/.config/PyLossless Studio/logs`
- macOS: `~/Library/Application Support/PyLossless Studio/logs`

Raport błędu zawiera między innymi:

- datę i godzinę,
- wersję aplikacji,
- komunikat błędu,
- traceback,
- kontekst operacji.

## Obsługa błędów

Program ma teraz trzy poziomy obsługi problemów:

- błędy zadań roboczych podczas kompresji, dekompresji albo testu integralności,
- globalne, nieobsłużone wyjątki z głównego wątku, wątków Pythona i callbacków Tkinter,
- błędy bootstrapu zależności, czyli brak pakietów z `requirements.txt` albo nieudana instalacja przez `pip`.

Jeśli coś pójdzie nie tak, użytkownik dostaje komunikat w GUI, a szczegółowy raport trafia do pliku `.txt`.

## Testy

Uruchomienie testów:

```bash
python -m unittest discover -s tests -v
```

Aktualne testy sprawdzają między innymi:

- poprawny round-trip tekstu,
- zachowanie dekompresji przy błędnym kodowaniu tekstu w nagłówku,
- wykrywanie niezgodności rozmiaru w teście integralności,
- tworzenie raportów błędów `.txt`,
- odczyt `requirements.txt` i logikę bootstrapu zależności.

## Porządki w plikach

W projekcie zostały usunięte zbędne pliki pomocnicze, które dublowały aktualną logikę lub nie były już używane:

- `Code/code.py` - zastąpiony przez jeden launcher `launcher.py`,
- `Code/pylossless/settings.py` - nieużywany po przeniesieniu obsługi ustawień do GUI.
