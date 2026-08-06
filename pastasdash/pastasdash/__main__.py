"""Start het dashboard met ``python -m pastasdash``.

Nodig naast het ``pastasdash``-commando: op werkplekken met een strenge
virusscanner wordt een vers aangemaakt ``pastasdash.exe`` in de ``.venv``
geblokkeerd (``Failed to spawn: Toegang geweigerd``, os error 5). Dat treft
juist de eerste start na klonen. Via ``python -m`` komt er geen nieuw
uitvoerbaar bestand aan te pas en start het dashboard wel.
"""

from pastasdash.cli import cli_main

if __name__ == "__main__":
    cli_main()
