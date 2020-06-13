""" stand alone command line script for use with pyinstaller
    
    To build this into an executable:
    - install pyinstaller:
        python3 -m pip install pyinstaller
    - then use make_cli_exe.sh to run pyinstaller or execute the following command:
        pyinstaller --onefile --hidden-import="pkg_resources.py2_warn" --name photosmeta cli.py

    Resulting executable will be in "dist/photosmeta"

    Note: This is *not* the cli that "python3 -m pip install photosmeta" or "python setup.py install" would install;
    it's merely a wrapper around __main__.py to allow pyinstaller to work
    
"""

from photosmeta.__main__ import main

if __name__ == "__main__":
    main()
