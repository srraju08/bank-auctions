# Run the scraper on your Windows PC (one-time setup, about 15 minutes)

BAANKNET blocks GitHub's servers, so the daily job runs on your PC instead.
GitHub still hosts the website. Your PC only does the collecting.

## 1. Install two programs (skip if already installed)

- **Python 3.12** from python.org/downloads. On the first installer screen, tick
  **"Add python.exe to PATH"**. Then choose **Customize installation → Next**, tick
  **"Install Python for all users"**, and click Install.
- **Git for Windows** from git-scm.com. Keep all the defaults.

## 2. Connect your PC to GitHub

1. Open github.com/srraju08/bank-auctions → **Settings → Actions → Runners →
   New self-hosted runner**, and choose **Windows** / **x64**.
2. Open **PowerShell as Administrator**. Start menu → type PowerShell → right-click →
   *Run as administrator*.
3. Copy the commands GitHub shows under **Download** and paste them in one block at a time.
   They create `C:\actions-runner` and download the runner.
4. Copy the **Configure** command (`./config.cmd --url ... --token ...`) and run it.
   When it asks questions:
   - Runner group, name, labels, work folder → press **Enter** to accept the defaults
   - "Would you like to run the runner as service?" → type **Y**
   - Service account → press **Enter** (keeps the default)
5. Back on GitHub, the **Runners** page should show your PC as **Idle** with a green dot.

That's it. The first scrape starts automatically within a minute. It's already
queued and waiting for your PC.

## How it behaves day to day

- The job is scheduled for 06:47 IST. If your PC is off or asleep then, GitHub keeps
  the job waiting for up to 24 hours. It runs as soon as the PC is back on.
- It runs in the background as a Windows service. You don't need to open anything.
- A full run takes 10–40 minutes and uses very little CPU.
- To pause it, open **Services** in Windows and stop the service named
  "GitHub Actions Runner".

## If something goes wrong

Open **Actions** in the repo and click the latest run to see its log. Send me
a screenshot of the red step if there is one.
