#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'


from datetime import datetime

import endpoints
import logging

from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException
from models import Profile, ProfileMiniForm, ProfileForm
from models import BooleanMessage
from models import Conference, ConferenceForm, ConferenceForms
from models import ConferenceQueryForm, ConferenceQueryForms
from models import Session, SessionForm, SessionForms
from models import TeeShirtSize
from models import StringMessage

from utils import getUserId

from settings import WEB_CLIENT_ID

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
MEMCACHE_FEATURED_KEY = "FEATURED_SPEAKER"


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESH_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

SESH_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1),
)

SESH_QUERY_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    typeOfSession=messages.StringField(2),
)

SPEAKER_QUERY_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker=messages.StringField(1),
)

WISHLIST_POST_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    SessionKey = messages.StringField(1),
)

DATE_QUERY_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    date=messages.StringField(1),
)

STARTTIME_QUERY_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    startTime=messages.StringField(1),
)
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', 
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID],
    scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        if field == 'teeShirtSize':
                            setattr(prof, field, str(val).upper())
                        else:
                            setattr(prof, field, val)
            prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf


    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # TODO 2: add confirmation email sending task to queue
        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )

        return request


    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)


    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)


    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id =  getUserId(user)
        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, getattr(prof, 'displayName')) for conf in confs]
        )


    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, names[conf.organizerUserId]) for conf in \
                conferences]
        )

# - - - Session objects - - - - - - - - - - - - - - - - -

#  ------------
#  |  TASK 1  |
#  ------------
    def _copySessionToForm(self, sesh):
        """Copy relevant fields from Session to SessionForm"""
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(sesh, field.name):
                # convert Time or Date to date string; just copy others
                if field.name.endswith(('startTime', 'date')):
                    setattr(sf, field.name, str(getattr(sesh, field.name)))
                else:
                    setattr(sf, field.name, getattr(sesh, field.name))
            elif field.name == "seshWebSafeKey":
                setattr(sf, field.name, sesh.key.urlsafe())

        sf.check_initialized()

        print sf
        return sf

#  ------------
#  |  TASK 1  |
#  ------------
    def _createSessionObject(self, request):
        """Create or update Session Object, returning SessionForm/request"""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('endpoints.get_current_user() failed. Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.UnauthorizedException("Session 'name' field required")

        if not request.websafeConferenceKey:
            raise endpoints.BadRequestException("Session 'websafeConferenceKey' field required")
        
        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can add sessions.')

        # copy SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['seshWebSafeKey']
        del data['websafeConferenceKey']

        # Convert dates from strings to Date objects; 
        if data['date']:
            data['date'] = datetime.strptime(data['date'][:10], "%Y-%m-%d").date()
        # Convert times from strings to time objects; 
        if data['startTime']:
            data['startTime'] = datetime.strptime(data['startTime'][:5], "%H:%M").time()
        
        # define session ancestor key
        # generate sesion key based on conference key
        c_key = ndb.Key(urlsafe=request.websafeConferenceKey)
        s_id = Session.allocate_ids(size=1, parent=c_key)[0]
        s_key = ndb.Key(Session, s_id, parent=c_key)

        # create session
        sesh = Session(
            key             = s_key,
            name            = data['name'],
            highlights      = data['highlights'],
            speaker         = data['speaker'],
            duration        = data['duration'],
            typeOfSession   = data['typeOfSession'],
            date            = data['date'],
            startTime       = data['startTime'],
        )

        sesh.put()

        taskqueue.add(
            url='/tasks/get_featured_speaker',
            params={'websafeConferenceKey': request.websafeConferenceKey, 
                    'speaker': data['speaker']}, 
            method='GET',
        )

        return self._copySessionToForm(sesh)

    @endpoints.method(SESH_POST_REQUEST, SessionForm,
        path='createSession/{websafeConferenceKey}',
        http_method='POST',
        name='createSession')
    def createSession(self, request):
        """Create new Session"""
        return self._createSessionObject(request)

    @endpoints.method(SESH_GET_REQUEST, SessionForms,
        path='getConferenceSessions/{websafeConferenceKey}',
        http_method='GET',
        name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Given a conference, return all sessions"""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id =  getUserId(user)

        conf = ndb.Key(urlsafe=request.websafeConferenceKey)
        print "1. This is the conf: ", conf

        # create ancestor query for all key matches for this user
        sessions = Session.query(ancestor=conf)
        print "2. This is the sessions object: ", sessions

        # return set of SessionForm objects per Session
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(SESH_QUERY_REQUEST, SessionForms,
            path='getConferenceSessionsByType/{websafeConferenceKey}',
            http_method='GET',
            name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Given a conference, return all sessions of a specified type"""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id =  getUserId(user)

        conf = ndb.Key(urlsafe=request.websafeConferenceKey)

        # create ancestor query for all key matches for this user
        sessions = Session.query(ancestor=conf)

        sessions = Session.query(Session.typeOfSession == request.typeOfSession)
           
        # return set of SessionForm objects per Session by type
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(SPEAKER_QUERY_REQUEST, SessionForms,
            path='getSessionsBySpeaker',
            http_method='GET',
            name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """Given a speaker, return all sessions given by this particular speaker, across all conferences"""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id =  getUserId(user)

        sessions = Session.query(Session.speaker == request.speaker)

        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        ) 

#  ------------
#  |  TASK 3  |
#  ------------
    @endpoints.method(SessionForms, SessionForms,
            path='getSessions',
            http_method='GET',
            name='getSessions')
    def getSessions(self, request):
        """Return all sessions across all conferences"""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id =  getUserId(user)

        sessions = Session.query()

        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(DATE_QUERY_REQUEST, SessionForms,
            path='getSessionsByDate',
            http_method='GET',
            name='getSessionsByDate')
    def getSessionsByDate(self, request):
        """Given a Date, return all sessions on this Date, across all
         conferences"""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id =  getUserId(user)

        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # Convert dates from strings to Date objects; 
        if data['date']:
            data['date'] = datetime.strptime(data['date'][:10], "%Y-%m-%d").date()

        sessions = Session.query(Session.date == data['date'])

        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(STARTTIME_QUERY_REQUEST, SessionForms,
            path='getSessionsByTime',
            http_method='GET',
            name='getSessionsByTime')
    def getSessionsByTime(self, request):
        """Given a time, return all sessions at this time, across all
         conferences"""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id =  getUserId(user)

        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # Convert times from strings to time objects;  
        if data['startTime']:
            data['startTime'] = datetime.strptime(data['startTime'][:5], "%H:%M").time()

        sessions = Session.query(Session.startTime == data['startTime'])

        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

# - - - WishList - - - - - - - - - - - - - - - - - - - -

#  ------------
#  |  TASK 2  |
#  ------------
    @ndb.transactional(xg=True)
    def _sessionWishlist(self, request, add=True):
        """Add or remove session to wishlist"""
        retval = None
        # Get session profile
        prof = self._getProfileFromUser()
        print "1. This is the users profile: ", prof

        # Check if sesh exists given websafeSeshKey
        wssk = request.SessionKey
        print "2. This is the request.sessionkey: ", wssk
        sesh = ndb.Key(urlsafe=wssk).get()
        print "3. This is the sesh: ", sesh
        if not sesh:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % wssk)

        # adding
        if add:
            if wssk in prof.sessionsToWishlist:
                raise ConflictException("Session already added to wishlist")

            prof.sessionsToWishlist.append(wssk)
            retval = True

        # removing
        else:
            # check if session already in wishlist
            if wssk in prof.sessionsToWishlist:
                # remove from wishlist
                prof.sessionsToWishlist.remove(wssk)
                retval = True
            else:
                retval = False

        # write things back to datastore & return
        prof.put()

        return BooleanMessage(data=retval)

    @endpoints.method(WISHLIST_POST_REQUEST, BooleanMessage,
            path='session/addToWishlist/{SessionKey}',
            http_method='POST', 
            name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Add session to a wishlist"""
        return self._sessionWishlist(request)

    @endpoints.method(WISHLIST_POST_REQUEST, BooleanMessage,
            path='session/{SessionKey}',
            http_method='DELETE', 
            name='deleteSessionInWishlist')
    def deleteSessionInWishlist(self, request):
        """Delete session from wishlist"""
        return self._sessionWishlist(request, add=False)

    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='session/wishlist',
            http_method='GET', 
            name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """Get list of sessions in wishlist"""
        prof = self._getProfileFromUser() # get user profile
        sesh_keys = [ndb.Key(urlsafe=wssk) for wssk in prof.sessionsToWishlist]
        sessions = ndb.get_multi(sesh_keys)

        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None

        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser() # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])\
         for conf in conferences]
        )


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -
    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & getAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = '%s %s' % (
                'Last chance to attend! The following conferences '
                'are nearly sold out:',
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement


    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET',
            name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        # TODO 1
        # return an existing announcement from Memcache or an empty string.
        announcement = memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY)
        if not announcement:
            announcement = ""
        return StringMessage(data=announcement)

#  ------------
#  |  TASK 4  |
#  ------------
    @staticmethod
    def _cacheFeaturedSpeaker(websafeConferenceKey, speaker):
        """Assign featured speaker to memcache"""
        #logging.info('1: This is the websafeConferenceKey: ' + websafeConferenceKey)
        #logging.info('2: This is the speaker: ' + speaker)
        
        conf = ndb.Key(urlsafe=websafeConferenceKey)

        print "3. This is the conf: ", conf

        sessions = Session.query(ancestor=conf)

        sessions = Session.query(Session.speaker == speaker).fetch()
        
        count = len(sessions)

        if count > 1:
            featured = 'Todays featured speaker is %s at session %s' %\
             (speaker, ', '.join(session.name for session in sessions))
            memcache.set(MEMCACHE_FEATURED_KEY, featured)
        else:
            # If there are is no featured speaker,
            # delete the memcache featured entry
            featured = ""
            memcache.delete(MEMCACHE_FEATURED_KEY)

        return featured

    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='session/featured/get',
            http_method='GET', 
            name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Return featured speaker from memcache."""
        featured = memcache.get(MEMCACHE_FEATURED_KEY)
        if not featured:
            featured = ""
        return StringMessage(data=featured)

api = endpoints.api_server([ConferenceApi]) # register API
