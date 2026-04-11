# pyinstaller command

pyinstaller not find serial need add hidden-import path.

command:
pyinstaller --onefile -F --hidden-import=serial --paths=".\.venv\Lib\site-packages" ".\Python\96check box_Pixel_96.py"