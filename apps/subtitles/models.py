# -*- coding: utf-8 -*-
# Amara, universalsubtitles.org
#
# Copyright (C) 2012 Participatory Culture Foundation
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more
# details.
#
# You should have received a copy of the GNU Affero General Public License along
# with this program.  If not, see http://www.gnu.org/licenses/agpl-3.0.html.

"""Django models represention subtitles."""

import datetime
import itertools

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import simplejson as json
from django.utils.translation import ugettext_lazy as _

from apps.auth.models import CustomUser as User
from apps.videos.models import Video
from babelsubs.storage import SubtitleSet
from babelsubs import load_from

from utils.compress import compress, decompress

ALL_LANGUAGES = sorted([(val, _(name)) for val, name in settings.ALL_LANGUAGES],
                       key=lambda v: v[1])


# Utility functions -----------------------------------------------------------
def mapcat(fn, iterable):
    """Mapcatenate.

    Map the given function over the given iterable.  Each mapping should result
    in an interable itself.  Concatenate these results.

    E.g.:

        foo = lambda i: [i, i+1]
        mapcatenate(foo, [20, 200, 2000])
        [20, 21, 200, 201, 2000, 2001]

    """
    return itertools.chain.from_iterable(itertools.imap(fn, iterable))

def ensure_stringy(val):
    """Ensure the given value is a stringy type, like str or unicode.

    If not, a ValidationError will be raised.

    This method is necessary because Django will often do the wrong thing when
    you pass a non-stringy object to a CharField (it will str() the object which
    probably isn't what you want).

    """
    if val == None:
        return

    if not (isinstance(val, str) or isinstance(val, unicode)):
        raise ValidationError('Value must be a string.')

def graphviz(video):
    """Return the dot code for a Graphviz visualization of a video's history."""

    lines = []

    lines.append("digraph video_%s {" % video.video_id)
    lines.append("rankdir = BT;")

    def _name(sv):
        return '%s%d' % (sv.language_code, sv.version_number)

    for sl in video.newsubtitlelanguage_set.all():
        for sv in sl.subtitleversion_set.all():
            lines.append('%s[label="%s"];' % (_name(sv), _name(sv)))

    for sl in video.newsubtitlelanguage_set.all():
        for sv in sl.subtitleversion_set.all():
            for pv in sv.parents.all():
                lines.append("%s -> %s;" % (_name(pv), _name(sv)))

    lines.append("}")

    return lines

def print_graphviz(video_id):
    video = Video.objects.get(video_id=video_id)
    print '\n'.join(graphviz(video))


# Lineage functions -----------------------------------------------------------
def lineage_to_json(lineage):
    return json.dumps(lineage)

def json_to_lineage(json_lineage):
    return json.loads(json_lineage)

def get_lineage(parents):
    """Return a lineage map for a version that has the given parents."""
    lineage = {}

    # The new version's lineage should be the result of merging the parents'
    # lineages, taking the later version whenever there's a conflict, and adding
    # the parent versions themselves to the map.
    for parent in parents:
        l, v = parent.language_code, parent.version_number

        if l not in lineage or lineage[l] < v:
            lineage[l] = v

        for l, v in parent.lineage.items():
            if l not in lineage or lineage[l] < v:
                lineage[l] = v

    return lineage


# SubtitleLanguages -----------------------------------------------------------
class SubtitleLanguageManager(models.Manager):
    def having_versions(self):
        """Return a QS of SLs that have at least 1 version.

        TODO: See if we need to denormalize this into a field.  I don't think we
        will (and would strongly prefer not to (see the has_version/had_version
        mess we were in before)).

        """
        return self.get_query_set().extra(where=[
            """
            EXISTS
            (SELECT 1
               FROM subtitles_subtitleversion AS sv
              WHERE sv.subtitle_language_id = subtitles_subtitlelanguage.id)
            """,
        ])

    def not_having_versions(self):
        """Return a QS of SLs that have zero versions.

        TODO: See if we need to denormalize this into a field.  I don't think we
        will (and would strongly prefer not to (see the has_version/had_version
        mess we were in before)).

        """
        return self.get_query_set().extra(where=[
            """
            NOT EXISTS
            (SELECT 1
               FROM subtitles_subtitleversion AS sv
              WHERE sv.subtitle_language_id = subtitles_subtitlelanguage.id)
            """,
        ])


    def having_public_versions(self):
        """Return a QS of SLs that have at least 1 publicly-visible versions.

        TODO: See if we need to denormalize this into a field.  I don't think we
        will (and would strongly prefer not to (see the has_version/had_version
        mess we were in before)).

        """
        return self.get_query_set().extra(where=[
            """
            EXISTS
            (SELECT 1
               FROM subtitles_subtitleversion AS sv
              WHERE sv.subtitle_language_id = subtitles_subtitlelanguage.id
            AND NOT (    sv.visibility = 'private'
                     AND sv.visibility_override = '')
            AND NOT (sv.visibility_override = 'private'))
            """,
        ])

    def not_having_public_versions(self):
        """Return a QS of SLs that have zero publicly-visible versions.

        TODO: See if we need to denormalize this into a field.  I don't think we
        will (and would strongly prefer not to (see the has_version/had_version
        mess we were in before)).

        """
        return self.get_query_set().extra(where=[
            """
            NOT EXISTS
            (SELECT 1
               FROM subtitles_subtitleversion AS sv
              WHERE sv.subtitle_language_id = subtitles_subtitlelanguage.id
            AND NOT (    sv.visibility = 'private'
                     AND sv.visibility_override = '')
            AND NOT (sv.visibility_override = 'private'))
            """,
        ])

class SubtitleLanguage(models.Model):
    """SubtitleLanguages are the equivalent of a 'branch' in a VCS.

    These exist mostly to coordiante access to a language amongst users.  Most
    of the actual data for the subtitles is stored in the version themselves.

    """
    video = models.ForeignKey(Video, related_name='newsubtitlelanguage_set')
    language_code = models.CharField(max_length=16, choices=ALL_LANGUAGES)

    writelock_time = models.DateTimeField(null=True, blank=True,
                                          editable=False)
    writelock_owner = models.ForeignKey(User, null=True, blank=True,
                                        editable=False,
                                        related_name='writelocked_newlanguages')
    writelock_session_key = models.CharField(max_length=255, blank=True,
                                             editable=False)

    created = models.DateTimeField(editable=False)

    # Denormalized signoff/collaborator count fields.
    # These are stored here for speed of retrieval and filtering.  They are
    # updated in the update_signoff_counts() method, which is called from the
    # Collaborator .save() method.
    unofficial_signoff_count = models.PositiveIntegerField(default=0,
                                                           editable=False)
    official_signoff_count = models.PositiveIntegerField(default=0,
                                                         editable=False)
    pending_signoff_count = models.PositiveIntegerField(default=0,
                                                        editable=False)
    pending_signoff_unexpired_count = models.PositiveIntegerField(default=0,
                                                                  editable=False)
    pending_signoff_expired_count = models.PositiveIntegerField(default=0,
                                                                editable=False)

    objects = SubtitleLanguageManager()

    class Meta:
        unique_together = [('video', 'language_code')]


    def __unicode__(self):
        return 'SubtitleLanguage %s / %s / %s' % (
            (self.id or '(unsaved)'), self.video.video_id,
            self.get_language_code_display()
        )


    def save(self, *args, **kwargs):
        creating = not self.pk

        if creating and not self.created:
            self.created = datetime.datetime.now()

        return super(SubtitleLanguage, self).save(*args, **kwargs)


    def get_tip(self):
        """Return the tipmost version of this language (if any)."""

        versions = self.subtitleversion_set.order_by('-version_number')[:1]

        if versions:
            return versions[0]
        else:
            return None


    def _sanity_check_parents(self, version, parents):
        r"""Check that the given parents are sane for an SV about to be created.

        There are a few rules checked here.

        First, versions cannot have more than one parent from a single language.
        For example, the following is invalid:

            en fr

            1
            |\
            \ \
             \ 2
              \|
               1

        Second, a parent cannot have a parent that precedes something existing
        in its own lineage.  It's easiest to understand this with an example.
        The following is invalid:

            en fr
            3
            |\
            2 \
            |  \
            1   \
             \   |
              \  |
               2 |
               |/
               1

        This is invalid because English was based off of French version 2, and
        then you tried to say a later version was based on French version 1.
        
        If English version 3 had been based on French version 2 (or later) that
        would be have been okay.

        """

        # There can be at most one parent from any given language.
        if len(parents) != len(set([v.language_code for v in parents])):
            raise ValidationError(
                "Versions cannot have two parents from the same language!")

        for parent in parents:
            if parent.language_code in version.lineage:
                if parent.version_number < version.lineage[parent.language_code]:
                    raise ValidationError(
                        "Versions cannot have parents that precede parents in "
                        "their lineage!")


    def add_version(self, *args, **kwargs):
        """Add a SubtitleVersion to the tip of this language.

        You probably don't need this.  You probably want
        apps.subtitles.pipeline.add_subtitles instead.

        Does not check any writelocking -- that's up to the pipeline.

        """
        kwargs['subtitle_language'] = self
        kwargs['language_code'] = self.language_code
        kwargs['video'] = self.video

        tip = self.get_tip()

        version_number = ((tip.version_number + 1) if tip else 1)
        kwargs['version_number'] = version_number

        parents = (kwargs.pop('parents', None) or [])

        if tip:
            parents.append(tip)

        kwargs['lineage'] = get_lineage(parents)

        ensure_stringy(kwargs.get('title'))
        ensure_stringy(kwargs.get('description'))

        sv = SubtitleVersion(*args, **kwargs)

        self._sanity_check_parents(sv, parents)

        sv.full_clean()
        sv.save()

        for p in parents:
            sv.parents.add(p)

        return sv


    def update_signoff_counts(self):
        """Update the denormalized signoff count fields and save."""

        cs = self.collaborator_set.all()

        self.official_signoff_count = len(
            [c for c in cs if c.signoff and c.signoff_is_official])

        self.unofficial_signoff_count = len(
            [c for c in cs if c.signoff and (not c.signoff_is_official)])

        self.pending_signoff_count = len(
            [c for c in cs if (not c.signoff)])

        self.pending_signoff_expired_count = len(
            [c for c in cs if (not c.signoff) and c.expired])

        self.pending_signoff_unexpired_count = len(
            [c for c in cs if (not c.signoff) and (not c.expired)])

        self.save()

    def get_description(self):
        v = self.get_tip()

        if v:
            return v.description

        return self.video.description

    def get_title(self):
        v = self.get_tip()

        if v:
            return v.title

        return self.video.title

    def get_num_versions(self):
        return self.subtitleversion_set.count()

    def get_subtitle_count(self):
        tip = self.get_tip()
        if tip:
            return tip.get_subtitle_count()
        return 0


    def is_primary_audio_language(self):
        return self.video.primary_audio_language_code == self.language_code


    def versions_for_user(self, user):
        from teams.models import TeamVideo
        from teams.permissions import get_member

        try:
            team_video = (TeamVideo.objects.select_related('team')
                                           .get(video=self.video))
        except TeamVideo.DoesNotExist:
            team_video = None

        if team_video:
            member = get_member(user, team_video.team)

            if not member:
                return self.subtitleversion_set.public()

        return self.subtitleversion_set.all()


# SubtitleVersions ------------------------------------------------------------
class SubtitleVersionManager(models.Manager):
    def public(self):
        """Return a queryset of all publicly-visible versions."""
        return (self.get_query_set()
                    .exclude(visibility='private', visibility_override='')
                    .exclude(visibility_override='private'))

class SubtitleVersion(models.Model):
    """SubtitleVersions are the equivalent of a 'changeset' in a VCS.

    They are designed with a few key principles in mind.

    First, SubtitleVersions should be mostly immutable.  Once written they
    should never be changed, unless a team needs to publish or unpublish them.
    Any other changes should simply create a new version.

    Second, SubtitleVersions are self-contained.  There's a little bit of
    denormalization going on with the video and language_code fields, but this
    makes it much easier for a SubtitleVersion to stand on its own and will
    improve performance overall.

    Because they're (mostly) immutable, the denormalization is less of an issue
    than it would be otherwise.

    You should only create new SubtitleVersions through the `add_version` method
    of SubtitleLanguage instances.  This will ensure consistency and handle
    updating the parentage and version numbers correctly.

    """
    parents = models.ManyToManyField('self', symmetrical=False, blank=True)

    video = models.ForeignKey(Video)
    subtitle_language = models.ForeignKey(SubtitleLanguage)
    language_code = models.CharField(max_length=16, choices=ALL_LANGUAGES)

    visibility = models.CharField(max_length=10,
                                  choices=(('public', 'public'),
                                           ('private', 'private')),
                                  default='public')

    # Visibility override can be used by team admins to force a specific type of
    # visibility for a version.  If set, it takes precedence over, but does not
    # affect, the main visibility field.
    visibility_override = models.CharField(max_length=10, blank=True,
                                           choices=(('public', 'public'),
                                                    ('private', 'private')),
                                           default='')

    version_number = models.PositiveIntegerField(default=1)

    author = models.ForeignKey(User, default=User.get_anonymous,
                               related_name='newsubtitleversion_set')

    title = models.CharField(max_length=2048, blank=True)
    description = models.TextField(blank=True)
    note = models.CharField(max_length=512, blank=True, default='')

    created = models.DateTimeField(editable=False)

    # Subtitles are stored in a text blob, serialized as base64'ed zipped XML
    # (oh the joys of Django).  Use the subtitles property to get and set them.
    # You shouldn't be touching this field.
    serialized_subtitles = models.TextField(blank=True)

    # Lineage is stored as a blob of JSON to save on DB rows.  You shouldn't
    # need to touch this field yourself, use the lineage property.
    serialized_lineage = models.TextField(blank=True)

    objects = SubtitleVersionManager()

    def get_subtitles(self):
        """Return the SubtitleSet for this version.

        A SubtitleSet will always be returned.  It may be empty if there are no
        subtitles.

        """
        # We cache the parsed subs for speed.
        if self._subtitles == None:
            self._subtitles = load_from(decompress(self.serialized_subtitles),
                    type='dfxp').to_internal()

        return self._subtitles

    def set_subtitles(self, subtitles):
        """Set the SubtitleSet for this version.

        You have a few options here:

        * Passing None will set the subtitles to an empty set.
        * Passing a SubtitleSet will set the subtitles to that set.
        * Passing a string of XML will treat it as DXFP and set it directly.
        * Passing a vanilla list (or any iterable) of subtitle tuples will
          create a SubtitleSet from that.

        """
        # TODO: Fix the language code to use the proper standard.
        if subtitles == None:
            subtitles = SubtitleSet(self.language_code)
        elif isinstance(subtitles, str) or isinstance(subtitles, unicode):
            subtitles = SubtitleSet(self.language_code, initial_data=subtitles)
        elif isinstance(subtitles, SubtitleSet):
            pass
        else:
            try:
                i = iter(subtitles)
                subtitles = SubtitleSet.from_list(self.language_code, i)
            except TypeError:
                raise TypeError("Cannot create SubtitleSet from type %s"
                                % str(type(subtitles)))

        self.serialized_subtitles = compress(subtitles.to_xml())

        # We cache the parsed subs for speed.
        self._subtitles = subtitles


    def get_lineage(self):
        # We cache the parsed lineage for speed.
        if self._lineage == None:
            if self.serialized_lineage:
                self._lineage = json_to_lineage(self.serialized_lineage)
            else:
                self._lineage = {}

        return self._lineage

    def set_lineage(self, lineage):
        self.serialized_lineage = lineage_to_json(lineage)
        self._lineage = lineage

    lineage = property(get_lineage, set_lineage)

    class Meta:
        unique_together = [('video', 'language_code', 'version_number')]


    def __init__(self, *args, **kwargs):
        """Create a new SubtitleVersion.

        You probably don't need this.  You probably want
        apps.subtitles.pipeline.add_subtitles instead.  Or at the very least you
        want the add_version method of SubtitleLanguage instances.

        `subtitles` can be given in any of the forms supported by set_subtitles.

        `lineage` should be a Python dictionary describing the lineage of this
        version.

        """
        # This is a bit clumsy, but we need to handle the subtitles kwarg like
        # this for it to work properly.  If it's given, we set the subtitles
        # appropriately after we create the version object.  If it's not given,
        # we *don't* set the subtitles at all -- we just let the
        # serialized_subtitles field stay as it is.
        has_subtitles = 'subtitles' in kwargs
        subtitles = kwargs.pop('subtitles', None)

        lineage = kwargs.pop('lineage', None)

        super(SubtitleVersion, self).__init__(*args, **kwargs)

        self._subtitles = None
        if has_subtitles:
            self.set_subtitles(subtitles)

        self._lineage = None
        if lineage != None:
            self.lineage = lineage

    def __unicode__(self):
        return u'SubtitleVersion %s / %s / %s v%s' % (
            (self.id or '(unsaved)'), self.video.video_id,
            self.get_language_code_display(), self.version_number
        )


    def save(self, *args, **kwargs):
        creating = not self.pk

        if creating and not self.created:
            self.created = datetime.datetime.now()

        # Sanity checking of the denormalized data.
        assert self.language_code == self.subtitle_language.language_code, \
               "Version language code does not match Language language code!"

        assert self.video_id == self.subtitle_language.video_id, \
               "Version video does not match Language video!"

        return super(SubtitleVersion, self).save(*args, **kwargs)


    def get_ancestors(self):
        """Return all ancestors of this version.  WARNING: MAY EAT YOUR DB!

        Returning all ancestors of a version is very database-intensive, because
        we need to walk each relation.  It will make roughly l^b database calls,
        where l is the length of a branch of history and b is the "branchiness".

        You probably don't need this.  You probably want to use the lineage
        instead.  This is mostly here for sanity tests.

        """
        def _ancestors(version):
            return [version] + list(mapcat(_ancestors, version.parents.all()))

        return set(mapcat(_ancestors, self.parents.all()))

    def get_subtitle_count(self):
        return len([s for s in self.get_subtitles().subtitle_items()])


# Collaborators ---------------------------------------------------------------
class CollaboratorManager(models.Manager):
    def get_for(self, subtitle_language):
        return self.get_query_set().filter(subtitle_language=subtitle_language)

    def get_all_signoffs_for(self, subtitle_language):
        return self.get_for(subtitle_language).filter(signoff=True)

    def get_peer_signoffs_for(self, subtitle_language):
        return (self.get_all_signoffs_for(subtitle_language)
                    .filter(signoff_is_official=False))

    def get_official_signoffs_for(self, subtitle_language):
        return (self.get_all_signoffs_for(subtitle_language)
                    .filter(signoff_is_official=True))

    def get_unsignedoff_for(self, subtitle_language, include_expired=False):
        qs = self.get_for(subtitle_language).filter(signoff=False)

        if not include_expired:
            qs = qs.exclude(expired=True)

        return qs

class Collaborator(models.Model):
    """Collaborator models represent a user working on a specific language."""

    user = models.ForeignKey(User)
    subtitle_language = models.ForeignKey(SubtitleLanguage)

    signoff = models.BooleanField(default=False)
    signoff_is_official = models.BooleanField(default=False)
    expired = models.BooleanField(default=False)

    expiration_start = models.DateTimeField(editable=False)

    created = models.DateTimeField(editable=False)

    objects = CollaboratorManager()

    class Meta:
        unique_together = (('user', 'subtitle_language'),)


    def save(self, *args, **kwargs):
        creating = not self.pk

        if creating and not self.created:
            self.created = datetime.datetime.now()

        if creating and not self.expiration_start:
            self.expiration_start = self.created

        result = super(Collaborator, self).save(*args, **kwargs)

        # Update the denormalized signoff count fields for SubtitleLanguages.
        # This has to be done after we've saved this Collaborator so the changes
        # will take effect.
        self.subtitle_language.update_signoff_counts()

        return result


