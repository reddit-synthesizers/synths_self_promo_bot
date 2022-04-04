from string import Template

import datetime
import os
import praw

DEFAULT_SUBREDDIT_NAME = 'synthesizers'
THREAD_TITLE = 'Self-Promotion Roundup'

MINUTES_TO_WARN = 5
MINUTES_TO_REMOVE = 120
MIN_COMMENTS_TO_START_ENFORCING = 5


class SynthsSelfPromoBot:
    def __init__(self, subreddit_name=DEFAULT_SUBREDDIT_NAME, dry_run=False):
        self.dry_run = dry_run

        self.reddit = praw.Reddit('SynthsSelfPromoBot')
        self.subreddit = self.reddit.subreddit(subreddit_name)

        self.warning_template = Template(
            self.read_text_file('self-promo-warning.txt'))
        self.removal_template = Template(
            self.read_text_file('self-promo-removal.txt'))

    def scan(self):
        submissions = self.subreddit.hot(limit=2)  # thread will be stickied in the hot 2
        self_promo = self.find_self_promo_submission(submissions)

        # wait until there's a minimum set of top-level comments before enforcing
        if (self_promo is not None and len(self_promo.comments) >= MIN_COMMENTS_TO_START_ENFORCING):
            self.process_submission(self_promo)

    # Find the self promo thread. If active, it's in the top 2 of the hot stream, and stickied.
    @staticmethod
    def find_self_promo_submission(submissions):
        self_promo = None

        for submission in submissions:
            if (submission.distinguished
                    and submission.stickied
                    and submission.title.startswith(THREAD_TITLE)):
                self_promo = submission
                break

        return self_promo

    # Walk through the top-level comments and warn anyone who did not leave a comment elswhere in the thread
    def process_submission(self, submission):
        submission.comments.replace_more(limit=None)

        for comment in submission.comments:
            self.process_comment(submission, comment)

    def process_comment(self, submission, comment):
        # don't act on distinguished mod or deleted comments
        if comment.distinguished is not None or self.is_comment_deleted(comment):
            return

        age = self.get_comment_age(comment)
        actionable = self.is_comment_actionable(submission, comment)
        was_warned = self.was_warned(comment)

        if age >= MINUTES_TO_REMOVE and actionable and was_warned:
            self.remove(comment)
        elif age >= MINUTES_TO_WARN and not actionable and was_warned:
            self.cleanup(comment)
        elif age >= MINUTES_TO_WARN and actionable and not was_warned:
            self.warn(comment)

    def remove(self, comment):
        warning_comment = self.find_warning_comment(comment)
        warning_comment_age = self.get_comment_age(warning_comment)

        # defer removal until the user has been warned for some time
        # this avoids the first commentors being punished with removal
        # when the MIN_COMMENTS_TO_START_ENFORCING limit is reached
        if warning_comment_age >= MINUTES_TO_REMOVE:
            self.log('Remove', comment)

            if not self.dry_run:
                self.remove_warning_comment(comment)

                comment.mod.remove(
                    spam=False, mod_note='OP did not participate in thread.')

                message = self.removal_template.substitute(hours=int(MINUTES_TO_REMOVE / 60))
                comment.mod.send_removal_message(message, 'Lack of contribution', 'private')

    def cleanup(self, comment):
        self.log('Cleanup', comment)

        if not self.dry_run:
            comment.mod.approve()
            self.remove_warning_comment(
                comment, 'OP participated in thread, removed warning.')

    def warn(self, comment):
        if not self.was_warned(comment):
            self.log('Warn', comment)

            if not self.dry_run:
                messaage = self.warning_template.substitute(
                    author=comment.author.name, hours=int(MINUTES_TO_REMOVE / 60))
                bot_comment = comment.reply(messaage)
                bot_comment.mod.distinguish(sticky=True)
                bot_comment.mod.ignore_reports()

    # determine if the user has replied to any comment tree in the thread outside of their own
    def is_comment_actionable(self, submission, comment):
        if (comment.approved  # dont act on mod approved, distinguished, removed, or deleted comments
                or comment.distinguished == 'moderator'
                or comment.removed
                or self.is_comment_deleted(comment)):
            return False

        users_self_promo_comments = set()  # find all comments in the self-promo thread by the user
        users_new_comments = self.reddit.redditor(
            comment.author.name).comments.new(limit=100)  # this might not scale with really active users

        for new_comment in users_new_comments:  # collect all of this user's comments in the self promo thread
            if (new_comment.submission.id == submission.id  # a comment's submission id is the submission it's in
                    and not new_comment.parent_id.startswith('t3_')):  # t3_ indicates a top-level comment
                users_self_promo_comments.add(new_comment)

        comment.replies.replace_more(limit=None)  # get the user's commment's reply tree
        discard_comments = comment.replies.list()
        discard_comments.append(comment)  # append the top-level comment
        diff = users_self_promo_comments.difference(set(discard_comments))  # the diff is all other comments

        return len(diff) == 0

    # return comment age in minutes
    @staticmethod
    def get_comment_age(comment):
        now = datetime.datetime.now()
        created = datetime.datetime.fromtimestamp(comment.created_utc)
        age = now - created
        return age.total_seconds() / 60

    @staticmethod
    def is_comment_deleted(comment):
        return (comment.collapsed_reason_code == 'DELETED'
                or comment.author is None
                or comment.body == '[deleted]')

    def find_warning_comment(self, comment):
        warning_comment = None

        if len(comment.replies) == 0:
            comment.refresh()

        for reply in comment.replies:
            if (reply.author.name == self.reddit.user.me()
                    and not reply.removed
                    and reply.distinguished == 'moderator'):
                warning_comment = reply
                break

        return warning_comment

    def was_warned(self, comment):
        return self.find_warning_comment(comment) is not None

    def remove_warning_comment(self, comment, mod_note=''):
        reply = self.find_warning_comment(comment)

        if reply is not None:
            reply.mod.remove(spam=False, mod_note=mod_note)

    @staticmethod
    def read_text_file(filename):
        with open(filename, encoding='utf-8') as file:
            text = file.read()

        return text

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
