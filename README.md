# 🎮 l2j-interlude-toolkit - Easy Server Setup and Management

[![Download l2j-interlude-toolkit](https://img.shields.io/badge/Download-l2j--interlude--toolkit-blue?style=for-the-badge)](https://github.com/jervilangel0/l2j-interlude-toolkit/releases)

---

## 📋 What is l2j-interlude-toolkit?

l2j-interlude-toolkit is a simple collection of tools made to help you run a Lineage 2 C6 Interlude private server. It includes a headless Python client, a multi-agent geodata scanner, a web dashboard, and server management features for L2J Mobius. If you want to manage your own server or explore Lineage 2 gameplay customization, this toolkit is designed to make the technical side easier to handle, even if you have little coding experience.

---

## 💻 System Requirements

To use l2j-interlude-toolkit smoothly, your computer should meet these basics:

- **Operating System:** Windows 10 or newer, macOS 10.15 (Catalina) or newer, or a recent Linux distribution.
- **Processor:** At least a 2 GHz dual-core CPU.
- **Memory:** Minimum of 4 GB RAM.
- **Storage:** At least 500 MB free disk space for the toolkit and any server files.
- **Internet:** Stable connection to download files and interact with remote services.
- **Python:** Requires Python 3.8 or later installed on your system.
- **Java:** Java Runtime Environment (JRE) 8 or newer, since the L2J Mobius server depends on Java.

If you are unsure about Python or Java versions installed on your system, we will cover how to check and install them below.

---

## 🚀 Getting Started

This section guides you step-by-step on how to download, set up, and run l2j-interlude-toolkit on your computer.

### 1. Download the Toolkit

First, go to the releases page to get the latest version.

[Visit the release page to download the toolkit](https://github.com/jervilangel0/l2j-interlude-toolkit/releases)

- Look for the latest version at the top.
- Download the ZIP file labeled for your operating system if available.

### 2. Install Python (if needed)

The toolkit uses Python to run the headless client and scanning agents.

- Check if Python is installed:  
  Open a command prompt (Windows) or terminal (macOS/Linux), then type:  
  ```
  python --version
  ```  
  or  
  ```
  python3 --version
  ```  
- If Python 3.8 or later is installed, you’re good to go.  
- Otherwise, download and install Python from https://www.python.org/downloads/  
  Make sure to check "Add Python to PATH" during installation on Windows.

### 3. Install Java (if needed)

The server tools require Java to function properly.

- Check if Java is installed:  
  Open a command prompt or terminal, then type:  
  ```
  java -version
  ```  
- You need at least Java 8 (also called Java 1.8).  
- If Java is missing or outdated, download it from https://adoptium.net/ or Oracle’s website.

### 4. Extract the Toolkit Files

Once you download the ZIP file:

- Find it in your Downloads folder.
- Right-click the ZIP file and select "Extract All..." on Windows or use built-in tools on macOS/Linux.
- Choose a location where you want to keep the toolkit folder (e.g., Desktop or Documents).

### 5. Install Required Python Packages

Open a command prompt or terminal, then navigate to the extracted folder. For example:

- On Windows, type:  
  ```
  cd Desktop\l2j-interlude-toolkit
  ```
- On macOS/Linux, type:  
  ```
  cd ~/Desktop/l2j-interlude-toolkit
  ```

Inside this folder, run the following to install dependencies:

```
pip install -r requirements.txt
```

This command installs the required Python modules to run the client and scanner.

---

## ⚙️ Running the Toolkit

After setup, here is how you start using the tools.

### Starting the Headless Python Client

The headless client allows you to interact with the game server remotely.

1. Open a command prompt or terminal.
2. Go to the toolkit folder.
3. Run this command:

```
python client.py
```

If the client connects successfully, you will see status messages with server info.

### Using the Multi-Agent Geodata Scanner

This tool scans Lineage 2 game maps to collect terrain data.

1. In the terminal, run:

```
python geodata_scanner.py
```

2. The scanner runs multiple agents in sequence. Wait until it finishes to collect data.
3. Data will be saved in a subfolder called "geodata".

### Accessing the Web Dashboard

The dashboard lets you manage your server via a browser.

1. Start the dashboard by running:

```
python dashboard.py
```

2. Open your favorite web browser.
3. Visit the address:

```
http://localhost:8080
```

4. Use the dashboard’s menus to manage and monitor your server.

---

## 🛠️ Configuration

To tailor the toolkit to your needs, find the config files in the `config` folder.

- `client_config.json` for client settings like server IP and user credentials.
- `scanner_config.json` to control scan areas and agent numbers.
- `dashboard_config.json` for dashboard web server settings.

You can open these files with any text editor (Notepad, TextEdit, VS Code) and change the values. Save the files after editing before running the programs.

---

## 📥 Download & Install

You can always get the latest stable version here:

[Visit the release page to download l2j-interlude-toolkit](https://github.com/jervilangel0/l2j-interlude-toolkit/releases)

### Download Steps Recap:

- Visit the release page link.
- Download the ZIP file for your platform.
- Extract contents to a folder.
- Install Python and Java if you do not have them.
- Open a terminal or command prompt in the extracted folder.
- Run `pip install -r requirements.txt` to set up Python dependencies.

---

## ❓ Troubleshooting

Here are some common issues and tips:

| Problem                        | Solution                                               |
|-------------------------------|--------------------------------------------------------|
| Python command not found       | Make sure Python is installed and added to your PATH. |
| Java version too old or missing| Install Java 8 or newer from trusted sources.          |
| Errors running Python scripts  | Confirm dependencies installed with `pip install`.    |
| Cannot connect to server       | Check your network connection and server address.     |
| Dashboard not loading in browser | Ensure you started `dashboard.py` and use correct URL.|

If you run into other issues, you may find help by opening a new discussion on the repository’s Issues page.

---

## 🔧 More About the Toolkit

l2j-interlude-toolkit helps you manage and customize a popular MMORPG server without digging deep into code. Its Python tools run quietly ("headless") to collect important terrain and gameplay data for better control. The web dashboard makes server management friendly for users who prefer point-and-click interfaces.

It fits best for people who want to experiment with private Lineage 2 servers, server owners with moderate technical knowledge, or anyone who likes to explore game development tools for MMORPGs.

---

## 🎯 Topics

This project relates to:

- Game development
- Game server management
- Geodata scanning
- Running headless clients
- Java and Python integration
- MMORPG private servers and terrain scanning

---

## © License

Check the repository for license details. Typically, open source projects allow free use but respect copyright terms.