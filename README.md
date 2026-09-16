<div align="center">

# 🎓 STUard

**Friendly student verification for the STU MTF Discord server**

Show you belong to STU, and get the right roles and channels automatically.

![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.7-5865F2?logo=discord&logoColor=white)

</div>

---

## ✨ What STUard does

- 🔐 **Checks that you really study or work at STU**, using your school account
- 🏷️ **Gives you the right roles**: student, applicant, teacher or graduate, plus your degree, programme and year
- 🚪 **Opens the channels that fit you**, like the ones for your year and programme
- 🙈 **Never sees your password**, and keeps as little about you as possible

## 🚀 Getting verified

```mermaid
flowchart TD
    start(["👋 You join the server"]) --> verify["Run /verify<br/>or click Overiť sa"]
    verify --> account{"Do you have a<br/>@stuba.sk account?"}
    account -- "Yes" --> ms["Sign in with Microsoft 365<br/>on STU's own page"]
    ms --> student["✅ Verified!<br/>Pick your degree, programme and year"]
    account -- "No, I'm an applicant" --> shot["Run /verify-manual with a<br/>screenshot of your e-prihláška"]
    shot --> mod["👀 A moderator checks it"]
    mod --> applicant["✅ You get the Uchádzač role"]
```

1. **Get your link.** Run `/verify` or click **Overiť sa** in the verification channel. Only you can see the link, and it works for 10 minutes.
2. **Confirm it's you on Discord.** The page checks that your browser is logged into the same Discord account, so nobody else can use your link.
3. **Sign in with your school account.** Click **Prihlásiť sa cez Microsoft 365** and log in with your `@stuba.sk` account. Your password goes only to STU's sign-in page.
4. **Pick your studies.** Choose your degree, programme and year with `/profile`, and your channels open up.

> 💡 **No Microsoft 365 button, or sign-in not working?** Run `/verify-manual` and upload a screenshot of your UIS portal instead. A moderator will take it from there.

## 🏷️ Roles you can get

| If you are… | You get |
|---|---|
| 🎒 a current student | **Študent**, plus your year (e.g. `2-BC`) and programme (e.g. `Bc. Mechatronika`) |
| 📝 an applicant | **Uchádzač** |
| 🧑‍🏫 a teacher | **Vyučujúci**, always confirmed by a moderator |
| 🎓 a graduate | **Absolvent** |
| 👋 no longer studying | **Bývalý študent**: you keep the general channels, but not the study ones |

## 🛡️ Your privacy

- 🔑 **Your password never reaches the bot.** You type it only on STU's own sign-in page.
- 🧮 **No name, email or AIS ID is stored.** The bot keeps a scrambled one-way fingerprint, only so that one school account can't verify two Discord accounts.
- 🖼️ **Screenshots are deleted** as soon as a moderator decides.
- 📦 **You're in control.** `/privacy` shows everything the bot keeps about you, and `/forget-me` deletes it.

## 💬 Commands

| Command | What it does |
|---|---|
| `/verify` | Get your personal sign-in link |
| `/verify-manual` | Verify with a screenshot (applicants, or when sign-in doesn't work) |
| `/profile` | See your status and set your degree, programme and year |
| `/privacy` | See the data the bot keeps about you |
| `/forget-me` | Delete your data and your verified roles |

## ❓ Questions

<details>
<summary><b>Does the bot see my password?</b></summary>
<br>

No. You sign in on STU's own login page, and the bot only receives confirmation of who you are and what kind of account you have. Your password never passes through the bot.

</details>

<details>
<summary><b>Why do I have to confirm my Discord account in the browser?</b></summary>
<br>

So your verification link is useless to anyone else. Even if someone got hold of it, they would have to be logged into your Discord account to use it.

</details>

<details>
<summary><b>I'm an applicant and don't have a school account yet</b></summary>
<br>

That's fine. Run `/verify-manual`, choose the applicant role and attach a screenshot of your e-prihláška. A moderator reviews it, and the screenshot is deleted right after.

</details>

<details>
<summary><b>Why am I asked to verify again?</b></summary>
<br>

Once a year, between 20 September and 31 October, everyone re-verifies so the roles stay accurate. You'll get reminders by DM before the deadline.

</details>

<details>
<summary><b>Something isn't working</b></summary>
<br>

Message a moderator on the server. They can look at your verification and help you out.

</details>

## 🛠️ Running your own copy

STUard is open source. To run it for your own server, follow the [setup guide](docs/SETUP.md).

## 📄 License

[GPL-3.0](LICENSE)
