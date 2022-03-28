# r/synthesizers rules bot

This bot monitors the weekly self-promotion thread. 

By default, it will monitor the thread for cases where a user did not comment on another user's submission.

After *5* minutes bot will leave a comment warning the user to post a comment.

After *120* minutes, if the user has not posted a comment on another person's submission, their submission will be removed.

# Installation

1. The only Python requirement is [PRAW](https://praw.readthedocs.io/en/stable/). Read the [installation](https://praw.readthedocs.io/en/stable/getting_started/installation.html) docs there for instructions on how to install.
2. You'll need to create a personal use script on [Reddit's app portal](https://ssl.reddit.com/prefs/apps/). The developer should be a mod on the subreddit that the bot will monitor.
3. Modify praw.ini with your client id and client secret (from Reddit's app portal) along with the developer's Reddit username and password.
4. The script is stateless and does its work in one pass. It's intended to run periodically via cron or AWS Lambda, etc.
