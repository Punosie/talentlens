// The setup manual, scene by scene. Used by record.mjs (video + screenshots) and booklet.mjs (PDF).
// `caption` is shown on screen in the video; `steps` / `body` go into the booklet.

export const INSTALL_COMMANDS = [
  'winget install --id GitHub.cli -e; winget install --id Git.Git -e',
  'gh auth login',
  'gh repo clone punosie/talentlens C:\\dev\\talentlens',
  'cd C:\\dev\\talentlens',
  'powershell -ExecutionPolicy Bypass -File scripts\\setup.ps1 -Invite "<your invite link>"',
]

export const JD_TEXT = `Senior Data Engineer - Bengaluru, India

We are a fintech company building lending and payments products.

Requirements
- 5-10 years of experience in data engineering
- Strong Python and SQL
- Apache Spark and Airflow
- AWS

Nice to have
- Kubernetes
- dbt`

export const SCENES = [
  {
    id: 'welcome', kind: 'card', section: 'Welcome',
    title: 'TalentLens: getting started',
    caption: 'Welcome! In a few minutes you will install TalentLens, connect to your team, and find the right people for a job.',
    body: 'TalentLens is a private search and job-matching app that runs on your own computer. This guide takes you from nothing installed to your first shortlist. You do not need any technical knowledge.',
  },
  {
    id: 'need', kind: 'card', section: 'Before you start',
    title: 'What you need',
    caption: 'You need a Windows 10 or 11 computer, an internet connection, about 4 GB of free space, and the invite link from your team.',
    steps: [
      'A Windows 10 or 11 computer (a Mac works too, see the note at the end).',
      'An internet connection for the first install. After that, TalentLens works offline.',
      'About 4 GB of free disk space (most of it is the local AI).',
      'Access to TalentLens on GitHub: ask the person who invited you to add you.',
      'Your invite link (it looks like https://…/join/…). Keep it private.',
    ],
  },
  {
    id: 'powershell', kind: 'card', section: 'Install',
    title: 'Open PowerShell',
    caption: 'Press the Windows key, type PowerShell, and press Enter. A blue or black window opens.',
    steps: ['Press the Windows key on your keyboard.', 'Type PowerShell.', 'Press Enter. A window with a blinking cursor opens.'],
  },
  {
    id: 'commands', kind: 'terminal', section: 'Install',
    title: 'Paste the install commands',
    caption: 'Copy each line, paste it into PowerShell (right-click), and press Enter. Put your invite link in the last line.',
    steps: [
      'Copy the first line, right-click inside PowerShell to paste, and press Enter. Wait until it finishes.',
      'Do the same for each following line, one at a time.',
      'gh auth login asks a few questions: choose GitHub.com, then HTTPS, then "Login with a web browser", and follow the browser.',
      'In the last line, replace <your invite link> with the link you received (keep the quotes).',
    ],
  },
  {
    id: 'setup-runs', kind: 'card', section: 'Install',
    title: 'Let setup finish',
    caption: 'Setup takes 5 to 15 minutes. It installs everything, measures your computer, and puts a TalentLens icon on your desktop.',
    steps: [
      'Setup downloads the local AI (about 2 GB) the first time. Leave the window open.',
      'It measures your computer and picks the fastest settings automatically (it uses an NVIDIA graphics card if you have one).',
      'When it says "TalentLens is ready", double-click TalentLens on your desktop.',
    ],
  },
  {
    id: 'onboarding', kind: 'app', section: 'First start',
    title: 'Choose your resume folder',
    caption: 'The first time TalentLens opens, pick the folder that holds your resumes. Your files are only read, never changed.',
    steps: [
      'TalentLens opens in your browser at http://127.0.0.1:8765. It runs only on your computer.',
      'Choose the folder with your resumes (PDF or Word). Click Browse… or paste the folder path.',
      'Click "Use this folder and continue". TalentLens reads your resumes in the background.',
      'You can change the folder later in Settings.',
    ],
  },
  {
    id: 'home', kind: 'app', section: 'First start',
    title: 'Your home screen',
    caption: 'This is your home screen. Next, connect to your team so their LinkedIn connections appear here too.',
    body: 'The left menu has everything: Search, Match to a job, Add resumes, Saved lists and Settings. The status at the top right shows what TalentLens is doing.',
  },
  {
    id: 'invite', kind: 'message', section: 'Connect to your team',
    title: 'Open your invite link',
    caption: 'Open the invite link your team sent you. Make sure TalentLens is open first.',
    steps: ['Keep TalentLens open.', 'Click the invite link you received (email, chat, etc.). It opens in your browser.'],
  },
  {
    id: 'join', kind: 'app', section: 'Connect to your team',
    title: 'Click "Connect TalentLens"',
    caption: 'On the invite page, click Connect TalentLens.',
    steps: [
      'The invite page explains what happens next.',
      'Click "Connect TalentLens". If the button does nothing, copy the link and paste it in TalentLens → Settings → Team connections.',
    ],
  },
  {
    id: 'confirm', kind: 'app', section: 'Connect to your team',
    title: 'Confirm in TalentLens',
    caption: 'TalentLens asks you to confirm the team address. Click Connect.',
    steps: ['TalentLens shows which team you are connecting to.', 'Click Connect. You only do this once on each computer.'],
  },
  {
    id: 'synced', kind: 'app', section: 'Connect to your team',
    title: 'Connections arrive automatically',
    caption: "Your team's connections now arrive in the background. You can see progress in Settings → Team connections.",
    steps: [
      'The first sync takes a few minutes for large teams. You can keep working meanwhile.',
      'It keeps itself up to date every 15 minutes. "Sync now" refreshes immediately.',
      'Resumes you add are shared with your team, linked to the right person.',
    ],
  },
  {
    id: 'search', kind: 'app', section: 'Use TalentLens',
    title: 'Search people',
    caption: 'Search anything: a role, a skill or a company. Use Show to see your resumes, LinkedIn connections, or both.',
    steps: [
      'Type a role, skill or company in the search box (press / to jump there).',
      'Narrow results with the filters on the left: skills, experience, location, industry.',
      'Use Show to switch between Everyone, Resumes and LinkedIn. "via @…" shows whose connection someone is.',
    ],
  },
  {
    id: 'profile', kind: 'app', section: 'Use TalentLens',
    title: 'Open a profile',
    caption: 'Click a person to see their details: experience, skills, education, and a link to their LinkedIn profile.',
    steps: ['Click any result to open the profile panel.', 'For LinkedIn connections, "Open on LinkedIn" takes you to their profile.', 'Press Esc or click outside to close.'],
  },
  {
    id: 'match-jd', kind: 'app', section: 'Match to a job',
    title: 'Paste a job description',
    caption: 'To find people for a job, open Match to a job and paste the job description.',
    steps: ['Click "Match to a job" in the left menu.', 'Paste the job description (or upload it as a file).', 'Click the button to read the requirements.'],
  },
  {
    id: 'match-req', kind: 'app', section: 'Match to a job',
    title: 'Check the requirements',
    caption: 'TalentLens reads the requirements for you. Check them, change anything you like, and click Show candidates.',
    steps: [
      'Must-have and nice-to-have skills, years of experience, location and industry are filled in for you.',
      'Remove or add anything. Choose whether to search your resumes, LinkedIn connections, or everyone.',
      'Click "Show candidates".',
    ],
  },
  {
    id: 'match-results', kind: 'app', section: 'Match to a job',
    title: 'Your ranked shortlist',
    caption: 'Everyone is ranked with a clear match label, a short reason, and the skills they have or are missing.',
    steps: [
      'The best matches are at the top. Each shows matched and missing must-have skills.',
      'Click "Why this score?" for a breakdown, or a name to open the profile.',
      'Select people to save a list or export it to Excel.',
    ],
  },
  {
    id: 'add', kind: 'app', section: 'Add resumes',
    title: 'Add new resumes',
    caption: 'Add resumes any time: choose files, a whole folder, or a ZIP. Duplicates are recognised automatically.',
    steps: [
      'Click "Add resumes" in the left menu.',
      'Choose files, a folder or a ZIP, or drag files onto the page.',
      'They become searchable within moments, and are shared with your team.',
    ],
  },
  {
    id: 'done', kind: 'card', section: 'You are all set',
    title: "You're all set",
    caption: 'That is it! Open TalentLens from your desktop any time. Need help? Ask the person who invited you.',
    steps: [
      'Open TalentLens from the desktop icon or the Start menu.',
      'Settings → Team connections: see sync status, Sync now, or Disconnect.',
      'Lost access? Ask for a new invite link and paste it in Settings.',
      'Everything, including the AI, runs on your computer.',
      'On a Mac: follow the README’s Mac steps and add --invite "<link>" to the setup command.',
    ],
  },
]
