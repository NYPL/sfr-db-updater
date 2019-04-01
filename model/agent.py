import re
from dateutil.parser import parse
from sqlalchemy import (
    Column,
    Date,
    ForeignKey,
    Integer,
    String,
    Unicode,
    or_
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

from model.core import Base, Core
from model.link import AGENT_LINKS, Link
from model.date import AGENT_DATES, DateField

from helpers.logHelpers import createLog
from helpers.errorHelpers import DataError

logger = createLog('agentModel')


class Agent(Core, Base):
    """An agent records an individual, organization, or family that is
    associated with the production of a FRBR entity (work, instance or item).
    Agents may be associated with one or more of these entities and can have
    multiple aliases and links (generally to Wikipedia or other reference
    sources).

    Agents are uniquely identifier by the VIAF and LCNAF authorities, though
    not all agents will have this data. Attempts to merge agents lacking
    authority control is made at the time of import."""

    __tablename__ = 'agents'
    id = Column(Integer, primary_key=True)
    name = Column(Unicode, index=True)
    sort_name = Column(Unicode, index=True)
    lcnaf = Column(String(25))
    viaf = Column(String(25))
    biography = Column(Unicode)

    aliases = relationship(
        'Alias',
        back_populates='agent'
    )
    links = relationship(
        'Link',
        secondary=AGENT_LINKS,
        back_populates='agents'
    )

    def __repr__(self):
        return '<Agent(name={}, sort_name={}, lcnaf={}, viaf={})>'.format(
            self.name,
            self.sort_name,
            self.lcnaf,
            self.viaf
        )

    @classmethod
    def updateOrInsert(cls, session, agent):
        """Evaluates whether a matching record exists and either updates that
        agent record or creates a new one"""
        aliases = agent.pop('aliases', [])
        roles = agent.pop('roles', [])
        link = agent.pop('link', [])
        dates = agent.pop('dates', [])

        agent.pop('birth_date', None)
        agent.pop('death_date', None)

        if roles is None:
            roles = []
        
        if dates is None:
            dates = []

        Agent._cleanName(agent, roles, dates)
        roles = list(set([ r.lower() for r in roles ]))
        if len(agent['name'].strip()) < 1:
            raise DataError('Received empty string for agent name')
        
        existingAgentID = Agent.lookupAgent(session, agent)
        if existingAgentID is not None:
            existingAgent = session.query(cls).get(existingAgentID)
            updated = Agent.update(
                session,
                existingAgent,
                agent,
                aliases=aliases,
                link=link,
                dates=dates
            )
            return updated, roles

        newAgent = Agent.insert(
            agent,
            aliases=aliases,
            link=link,
            dates=dates
        )

        return newAgent, roles

    @classmethod
    def update(cls, session, existing, agent, **kwargs):
        """Updates an existing agent record"""
        aliases = kwargs.get('aliases', [])
        link = kwargs.get('link', [])
        dates = kwargs.get('dates', [])

        for field, value in agent.items():
            if(value is not None and value.strip() != ''):
                setattr(existing, field, value)        

        if aliases is not None:
            aliasRecs = [
                Alias.insertOrSkip(session, a, Agent, existing.id)
                for a in aliases
            ]
            for alias in list(filter(None, aliasRecs)):
                existing.aliases.append(alias)

        if type(link) is dict:
            updateLink = Link.updateOrInsert(session, link, Agent, existing.id)
            if updateLink is not None:
                existing.links.append(updateLink)
        elif type(link) is list:
            for linkItem in link:
                updateLink = Link.updateOrInsert(session, linkItem, Agent, existing.id)
                if updateLink is not None:
                    existing.links.append(updateLink)

        for date in dates:
            updateDate = DateField.updateOrInsert(session, date, Agent, existing.id)
            if updateDate is not None:
                existing.dates.append(updateDate)

        return existing

    @classmethod
    def insert(cls, agentData, **kwargs):
        """Inserts a new agent record"""
        logger.debug('Inserting new agent record: {}'.format(agentData['name']))
        agent = Agent(**agentData)

        if agent.sort_name is None:
            # TODO Order sort_name in last, first order always
            agent.sort_name = agent.name

        aliases = kwargs.get('aliases', [])
        link = kwargs.get('link', [])
        dates = kwargs.get('dates', [])

        if aliases is not None:
            for alias in list(map(lambda x: Alias(alias=x), aliases)):
                agent.aliases.append(alias)

        if type(link) is list:
            for linkItem in link:
                newLink = Link(**linkItem)
                agent.links.append(newLink)
        elif type(link) is dict:
            newLink = Link(**link)
            agent.links.append(newLink)

        for date in dates:
            newDate = DateField.insert(date)
            agent.dates.append(newDate)

        return agent

    @classmethod
    def lookupAgent(cls, session, agent):
        """Queries the database for an agent record, using VIAF/LCNAF, and only
        if they are not present, the jaro_winkler algorithm for the agents
        name.

        Jaro-Winkler calculates string distance with a weight towards the
        characters at the start of a string, making it better suited to
        matching Last, First names than other string comparison algorithms."""

        if agent['viaf'] is not None or agent['lcnaf'] is not None:
            logger.debug('Matching agent on VIAF/LCNAF')
            try:
                return session.query(cls.id)\
                    .filter(
                        or_(
                            cls.viaf == agent['viaf'],
                            cls.lcnaf == agent['lcnaf']
                        )
                    )\
                    .one()
            
            except MultipleResultsFound:
                logger.error('Found multiple matching agents, should only be one record per identifier')
                raise
            except NoResultFound:
                pass

        logger.debug('Matching agent based off jaro_winkler score')
        
        escapedName = agent['name'].replace('\'', '\'\'')
        try:
            jaroWinklerQ = text(
                "jarowinkler({}, '{}') > {}".format('name', escapedName, 0.95)
            )
            return session.query(cls.id)\
                .filter(jaroWinklerQ)\
                .one()
            
        except MultipleResultsFound:
            logger.info('Name/information is too generic to create individual record')
            pass
        except NoResultFound:
            pass
        
        return None

    @classmethod
    def _cleanName(cls, agent, roles, dates):
        """Parse agent name to normalize and remove/assign roles/dates"""
        # Escape single quotes for postgres
        tmpName = agent['name']
        tmpName = tmpName.replace('\'', '\'\'')
        if re.match(r'^\[.+\]$', tmpName):
            tmpName = tmpName.strip('[]')

        # Parse and remove lifespan dates from the author name string
        lifeGroup = re.search(r'([0-9]{4})\-(?:([0-9]{4})|)', tmpName)
        if lifeGroup is not None:
            tmpName = tmpName.replace(lifeGroup.group(0), '')
            try:
                birthDate = lifeGroup.group(1)
                if birthDate is not None:
                    dates.append({
                        'display_date': birthDate,
                        'date_range': birthDate,
                        'date_type': 'birth_date'
                    })
            except IndexError:
                pass
            
            try:
                deathDate = lifeGroup.group(2)
                if deathDate is not None:
                    dates.append({
                        'display_date': deathDate,
                        'date_range': deathDate,
                        'date_type': 'death_date'
                    })
            except IndexError:
                pass

        # Parse and remove roles from the author name string
        roleGroup = re.search(r'\[([a-zA-Z; ]+)\]', tmpName)
        if roleGroup is not None:
            tmpName = tmpName.replace(roleGroup.group(0), '')
            tmpRoles = roleGroup.group(1).split(';')
            cleanRoles = [r.lower().strip() for r in tmpRoles]
            roles.extend(cleanRoles)
        
        # Strip punctuation from end of name string
        agent['name'] = tmpName.strip('.,;:|[]" ')
        agent['sort_name'] = agent['name']


class Alias(Core, Base):
    """Alternate, or variant names for an agent."""
    __tablename__ = 'aliases'
    id = Column(Integer, primary_key=True)
    alias = Column(Unicode, index=True)
    agent_id = Column(Integer, ForeignKey('agents.id'))

    agent = relationship('Agent', back_populates='aliases')

    def __repr__(self):
        return '<Alias(alias={}, agent={})>'.format(self.alias, self.agent)

    @classmethod
    def insertOrSkip(cls, session, alias, model, recordID):
        """Queries database for alias associated with current agent. If alias
        exists, we can skip this, no modification is needed. If it is not
        found, a new alias is created."""

        alias = alias.replace('\'', '\'\'')

        try:
            session.query(cls)\
                .join(model)\
                .filter(Alias.alias == alias)\
                .filter(model.id == recordID)\
                .one()
        except NoResultFound:
            return Alias(alias=alias)
