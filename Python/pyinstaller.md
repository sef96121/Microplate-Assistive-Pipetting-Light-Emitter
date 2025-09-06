# pyinstaller command

pyinstaller not find serial need add hidden-import path.

command:
pyinstaller --onefile -F --hidden-import=serial --paths="C:\Users\sef96\Dropbox\Case\Running\Microplate Assistive Pipetting Light Emitter\program\.venv\Lib\site-packages" .\96check_box.py