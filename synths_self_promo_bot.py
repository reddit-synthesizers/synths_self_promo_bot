import datetime
import json
import os
from string import Template

import praw

DEFAULT_SUBREDDIT_NAME = 'synthesizers'
THREAD_TITLE = 'Self-Promotion Roundup'

MINUTES_TO_WARN = 5
MINUTES_TO_REMOVE = 120
MIN_COMMENTS_TO_START_ENFORCING = 3


class SynthsSelfPromoBot:
    def __init__(self, subreddit_name=DEFAULT_SUBREDDIT_NAME, dry_run=False, reddit=None):
        self.dry_run = dry_run

        self.reddit = reddit if reddit else praw.Reddit('SynthsSelfPromoBot')
        self.subreddit = self.reddit.subreddit(subreddit_name)

        self.warning_template = Template(
            self.read_template_file('data/synths_self_promo_bot/self-promo-warning.txt'))
        self.removal_template = Template(
            self.read_template_file('data/synths_self_promo_bot/self-promo-removal.txt'))

        self.overrides = self.read_json_file('data/synths_self_promo_bot/self-promo-overrides.json')
        self.contributors_cache = None

    def scan(self):
        self_promo_submission = self.find_self_promo_submission()

        # wait until there's a minimum set of top-level comments before enforcing
        if (self_promo_submission is not None
                and len(self_promo_submission.comments) >= MIN_COMMENTS_TO_START_ENFORCING):
            self.contributors_cache = self.build_contributors_cache(self_promo_submission)
            self.process_submission(self_promo_submission)

    # Walk through the top-level comments and warn anyone who did not leave a comment elswhere in the thread
    def process_submission(self, submission):
        for comment in submission.comments:
            if self.is_comment_actionable(comment):
                self.process_comment(comment)

    def process_comment(self, comment):
        comment_age = self.get_comment_age(comment)
        user_contributed = self.did_user_contribute(comment)
        was_warned = self.was_warned(comment)

        if comment_age >= MINUTES_TO_REMOVE and not user_contributed and was_warned:
            self.remove(comment)
        elif comment_age >= MINUTES_TO_WARN and user_contributed and was_warned:
            self.cleanup(comment)
        elif comment_age >= MINUTES_TO_WARN and not user_contributed and not was_warned:
            self.warn(comment)

    def remove(self, comment):
        warning_comment = self.find_warning_comment(comment)
        warning_comment_age = self.get_comment_age(warning_comment)

        # defer removal until the user has been warned for some time
        # this avoids the first commentors being punished with removal
        # when the MIN_COMMENTS_TO_START_ENFORCING limit is reached
        if warning_comment_age >= MINUTES_TO_REMOVE:
            if not self.dry_run:
                self.remove_warning_comment(comment)
                comment.mod.remove(
                    spam=False, mod_note='OP did not participate in thread.')
                message = self.removal_template.substitute(
                    hours=int(MINUTES_TO_REMOVE / 60))
                comment.mod.send_removal_message(
                    message, 'Lack of contribution', 'private')

            self.log('Remove', comment)

    def cleanup(self, comment):
        if not self.dry_run:
            comment.mod.approve()
            self.remove_warning_comment(comment, 'OP participated in thread, removed warning.')

        self.log('Cleanup', comment)

    def warn(self, comment):
        if not self.dry_run:
            messaage = self.warning_template.substitute(
                author=comment.author.name, hours=int(MINUTES_TO_REMOVE / 60))
            bot_comment = comment.reply(messaage)
            bot_comment.mod.distinguish(sticky=True)
            bot_comment.mod.ignore_reports()

        self.log('Warn', comment)

    # Find the self promo thread. If active, it's in the top 2 of the hot stream, and stickied.
    def find_self_promo_submission(self):
        self_promo = None

        for submission in self.subreddit.hot(limit=2):  # thread will be stickied in the hot 2
            if (submission.stickied
                    and submission.title.startswith(THREAD_TITLE)):
                self_promo = submission
                break

        return self_promo

    # determine if the user has replied to any comment tree in the thread outside of their own
    def is_comment_actionable(self, comment):
        return not (comment.approved
                    or comment.distinguished == 'moderator'
                    or comment.removed
                    or self.is_comment_deleted(comment)
                    or comment.author in self.overrides["approved"])

    def did_user_contribute(self, comment):
        return comment.author.name in self.contributors_cache

    def was_warned(self, comment):
        return self.find_warning_comment(comment) is not None

    def find_warning_comment(self, comment):
        warning_comment = None

        if len(comment.replies) == 0:
            comment.refresh()

        for reply in comment.replies:
            if (reply.author.name == self.reddit.config.username
                    and not reply.removed
                    and reply.distinguished == 'moderator'):
                warning_comment = reply
                break

        return warning_comment

    def remove_warning_comment(self, comment, mod_note=''):
        reply = self.find_warning_comment(comment)

        if reply is not None:
            reply.mod.remove(spam=False, mod_note=mod_note)

    # create a set of all contributors who posted to comment threads outside of their own
    @staticmethod
    def build_contributors_cache(submission):
        cache = set()

        submission.comments.replace_more(limit=None)

        for comment in submission.comments:
            if comment.author is not None:
                top_level_author_name = comment.author.name
                for reply in comment.replies.list():
                    if reply.author is not None and reply.author.name != top_level_author_name:
                        cache.add(reply.author.name)

        return cache

    @staticmethod
    def get_comment_age(comment):
        now = datetime.datetime.now()
        created = datetime.datetime.fromtimestamp(comment.created_utc)
        age = now - created
        return int(age.total_seconds() / 60)

    @staticmethod
    def is_comment_deleted(comment):
        return (comment.collapsed_reason_code == 'DELETED'
                or comment.author is None
                or comment.body == '[deleted]')

    @staticmethod
    def read_template_file(filename):
        with open(filename, encoding='utf-8') as file:
            text = file.read()

        return text

    @staticmethod
    def read_json_file(filename):
        with open(filename, encoding='utf-8') as file:
            data = json.load(file)

        return data

    def log(self, action, comment):
        is_dry_run = '*' if self.dry_run is True else ''
        name = type(self).__name__
        now = datetime.datetime.now()
        print(f'{is_dry_run}[{name}][{now}] {action}: {comment.author.name} \'{comment.body[:15]}...\' ({comment.id})')


def lambda_handler(event=None, context=None):
    subreddit_name = os.environ['subreddit_name'] if 'subreddit_name' in os.environ else DEFAULT_SUBREDDIT_NAME
    dry_run = os.environ['dry_run'] == 'True' if 'dry_run' in os.environ else False
    self_promo_bot = SynthsSelfPromoBot(subreddit_name, dry_run)
    self_promo_bot.scan()


if __name__ == '__main__':
    lambda_handler()
