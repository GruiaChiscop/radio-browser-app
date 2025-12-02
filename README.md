# radio-browser-accessible-desktop-app

A minimal but fully functional radio player client that can stream any radio station from the radio-browser.info database, will later add support for multiple databases (onlineradiobox)
### Features
- Filtering and searching by Continent, Country and Language;
- Saving stations as favourite for easy access;
- Playing radio stations, it also allows copying the stream URL to clipboard;
- Recording: The client is able to record radio stations and save the file to disk;
-- Screen reader optimised: It uses the [https://github.com/accessibleapps/accessible_output2][accessible-output2] module to speak and braille the status messages;
- Auto update: The client checks and updates itself to the latest version;
- It theoretically supports changing the radio database source, but I haven't actually implemented it yet, it's just a place holder.
### Building
### Requirements
This project uses a python virtual environment (venv). While it's not mandatory, it's highly recommended.
```bash:
py -m venv .
scripts/activate
```
In the main repository directory, you'll find a "requirements.txt" file with all the modules the client needs. Run:
```bash:
pip install -r requirements.txt
```

Then you can:

```bash:
python radio_browser.py
```
to run the program.
**If you wish to build an executable, you can use [https://pyinstaller.org/en/stable/][pyinstaller] or any other similar module**.
```bash:
pyinstaller -w radio-browser.py
```
You should use the -w flag to compile the exe as a windows subsystem program, if you're running on windows, of course.
Also, to run the program, you'll need to grab the [https://www.un4seen.com/][Bass Audio] files, then place them inside the internal/pybass directory. Otherwise the app will throw an exception.
### Contributing to this project
If you find bugs or simply want to improve this project, do not hesitate to open issues or create a pull request. Any suggestion is wellcome.