import datetime
import os
import praw

from string import Template

DEFAULT_SUBREDDIT_NAME = 'synthesizers'
THREAD_TITLE = 'Self-Promotion Roundup'

MINUTES_TO_WARN = 5
MINUTES_TO_REMOVE = 120
MIN_COMMENTS_TO_START_ENFORCING = 5


class SynthsSelfPromoBot:
    def __init__(self, subreddit_name=DEFAULT_SUBREDDIT_NAME, dry_run=False):
        self.dry_run = dry_run

        self.warning_template = Template(
            self.read_text_file('self-promo-warning.txt'))
        self.removal_template = Template(
            self.read_text_file('self-promo-removal.txt'))

        self.reddit = praw.Reddit('SynthsSelfPromoBot')
        subreddit = self.reddit.subreddit(subreddit_name)

        # thread will be stickied in the hot 2
        submissions = subreddit.hot(limit=2)
        self_promo = self.find_self_promo_submission(submissions)

        if self_promo is not None and self_promo.comments.__len__() >= MIN_COMMENTS_TO_START_ENFORCING:
            self.process_submission(self_promo)

    # Find the self promo thread. If active, it's in the top 2 of the hot stream, and stickied.
    def find_self_promo_submission(self, submissions):
        self_promo = None

        for submission in submissions:
            if (submission.distinguished
                    and submission.stickied
                    and submission.title.startswith(THREAD_TITLE)):
                self_promo = submission

        return self_promo

    # Walk through the top-level comments and warn anyone who did not leave a comment elswhere in the thread
    def process_submission(self, submission):
        submission.comments.replace_more(limit=None)

        for comment in submission.comments:
            self.process_comment(submission, comment)

    def process_comment(self, submission, comment):
        # don't act on distinguished mod or deleted comments
        if (comment.distinguished is not None
                or self.is_comment_deleted(comment)):
            return

        age = self.get_comment_age(comment)
        was_warned = self.has_bot_warning(comment)

        if self.is_comment_actionable(submission, comment):
            if age > MINUTES_TO_REMOVE:
                self.remove(comment)
            elif age > MINUTES_TO_WARN:
                self.warn(comment)
        elif was_warned:
            self.cleanup(comment)

    def warn(self, comment):
        if not self.has_bot_warning(comment):
            self.log('Warn', comment)

            if not self.dry_run:
                messaage = self.warning_template.substitute(
                    author=comment.author.name, hours=int(MINUTES_TO_REMOVE / 60))

                bot_comment = comment.reply(messaage)
                bot_comment.mod.distinguish(sticky=True)
                bot_comment.mod.ignore_reports()

    def remove(self, comment):
        self.log('Remove', comment)

        if not self.dry_run:
            # clean up the bot's comments
            self.remove_bot_replies(comment)

            comment.mod.remove(mod_note='OP did not participate in thread.')

            message = self.removal_template.substitute(
                hours=int(MINUTES_TO_REMOVE / 60))
            comment.mod.send_removal_message(message, 'Lack of contribution', 'private')

    def cleanup(self, comment):
        self.log('Cleanup', comment)

        if not self.dry_run:
            self.remove_bot_replies(comment, 'OP participated in thread, removed warning.')
            comment.mod.approve()

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

        return (diff.__len__() == 0)

    # return comment age in minutes
    def get_comment_age(self, comment):
        now = datetime.datetime.now()
        created = datetime.datetime.fromtimestamp(comment.created_utc)
        age = now - created
        return age.total_seconds() / 60

    # I don't know of a better way
    def is_comment_deleted(self, comment):
        return (comment.collapsed_reason_code == 'DELETED'
                or comment.author is None
                or comment.body == '[deleted]')

    def find_bot_replies(self, comment):
        bot_comments = list()

        if comment.replies.__len__() == 0:
            comment.refresh()

        for reply in comment.replies:
            if (reply.author.name == self.reddit.user.me()
                    and reply.distinguished == 'moderator'
                    and not reply.removed):
                bot_comments.append(reply)

        return bot_comments

    def has_bot_warning(self, comment):
        return self.find_bot_replies(comment).__len__() > 0

    def remove_bot_replies(self, comment, mod_note=''):
        for reply in self.find_bot_replies(comment):
            reply.mod.remove(
                mod_note=mod_note)

    def read_text_file(self, filename):
        text = {}

        file = open(filename, 'r')
        text = file.read()
        file.close()

        return text

    def log(self, action, comment):
        now = datetime.datetime.now()
        name = type(self).__name__
        print(f'[{name}][{now}] {action}: {comment.author.name} \'{comment.body[:15]}...\' ({comment.id})')


if __name__ == '__main__':
    SynthsSelfPromoBot()


def lambda_handler(event, context):
    subreddit_name = os.environ['subreddit_name'] if 'subreddit_name' in os.environ else DEFAULT_SUBREDDIT_NAME
    dry_run = bool(os.environ['dry_run']) if 'dry_run' in os.environ else False
    SynthsSelfPromoBot(subreddit_name, dry_run)
