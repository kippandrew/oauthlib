"""
oauthlib.oauth2.draft_25
~~~~~~~~~~~~~~

This module is an implementation of various logic needed
for signing and checking OAuth 2.0 draft 25 requests.
"""
from oauthlib.common import add_params_to_uri, generate_token
from oauthlib.uri_validate import is_absolute_uri
from tokens import prepare_bearer_uri, prepare_bearer_headers
from tokens import prepare_bearer_body, prepare_mac_header
from parameters import prepare_grant_uri, prepare_token_request
from parameters import parse_authorization_code_response
from parameters import parse_implicit_response, parse_token_response


AUTH_HEADER = u'auth_header'
URI_QUERY = u'query'
BODY = u'body'


class Client(object):
    """Base OAuth2 client responsible for access tokens.

    While this class can be used to simply append tokens onto requests
    it is often more useful to use a client targeted at a specific workflow.
    """

    def __init__(self, client_id,
            default_token_placement=AUTH_HEADER,
            token_type=u'Bearer',
            access_token=None,
            refresh_token=None,
            **kwargs):
        """Initialize a client with commonly used attributes."""

        self.client_id = client_id
        self.default_token_placement = default_token_placement
        self.token_type = token_type
        self.access_token = access_token
        self.refresh_token = refresh_token

    @property
    def token_types(self):
        """Supported token types and their respective methods

        Additional tokens can be supported by extending this dictionary.

        The Bearer token spec is stable and safe to use.

        The MAC token spec is not yet stable and support for MAC tokens
        is experimental and currently matching version 00 of the spec.
        """
        return {
            u'Bearer': self._add_bearer_token,
            u'MAC': self._add_mac_token
        }

    def add_token(self, uri, http_method=u'GET', body=None, headers=None,
            token_placement=None):
        """Add token to the request uri, body or authorization header.

        The access token type provides the client with the information
        required to successfully utilize the access token to make a protected
        resource request (along with type-specific attributes).  The client
        MUST NOT use an access token if it does not understand the token
        type.

        For example, the "bearer" token type defined in
        [I-D.ietf-oauth-v2-bearer] is utilized by simply including the access
        token string in the request:

        GET /resource/1 HTTP/1.1
        Host: example.com
        Authorization: Bearer mF_9.B5f-4.1JqM

        while the "mac" token type defined in [I-D.ietf-oauth-v2-http-mac] is
        utilized by issuing a MAC key together with the access token which is
        used to sign certain components of the HTTP requests:

        GET /resource/1 HTTP/1.1
        Host: example.com
        Authorization: MAC id="h480djs93hd8",
                            nonce="274312:dj83hs9s",
                            mac="kDZvddkndxvhGRXZhvuDjEWhGeE="

        .. _`I-D.ietf-oauth-v2-bearer`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#ref-I-D.ietf-oauth-v2-bearer
        .. _`I-D.ietf-oauth-v2-http-mac`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#ref-I-D.ietf-oauth-v2-http-mac
        """
        token_placement = token_placement or self.default_token_placement

        if not self.token_type in self.token_types:
            raise ValueError("Unsupported token type: %s" % self.token_type)

        if not self.access_token:
            raise ValueError("Missing access token.")

        return self.token_types[self.token_type](uri, http_method, body,
                    headers, token_placement)

    def prepare_refresh_body(self, body=u'', refresh_token=None, scope=None):
        """Prepare an access token request, using a refresh token.

        If the authorization server issued a refresh token to the client, the
        client makes a refresh request to the token endpoint by adding the
        following parameters using the "application/x-www-form-urlencoded"
        format in the HTTP request entity-body:

        grant_type
                REQUIRED.  Value MUST be set to "refresh_token".
        refresh_token
                REQUIRED.  The refresh token issued to the client.
        scope
                OPTIONAL.  The scope of the access request as described by
                Section 3.3.  The requested scope MUST NOT include any scope
                not originally granted by the resource owner, and if omitted is
                treated as equal to the scope originally granted by the
                resource owner.
        """
        refresh_token = refresh_token or self.refresh_token
        return prepare_token_request(u'refresh_token', body=body, scope=scope,
                refresh_token=refresh_token)

    def _add_bearer_token(self, uri, http_method=u'GET', body=None,
            headers=None, token_placement=None):
        """Add a bearer token to the request uri, body or authorization header."""
        if token_placement == AUTH_HEADER:
            headers = prepare_bearer_headers(self.access_token, headers)

        elif token_placement == URI_QUERY:
            uri = prepare_bearer_uri(self.access_token, uri)

        elif token_placement == BODY:
            body = prepare_bearer_body(self.access_token, body)

        else:
            raise ValueError("Invalid token placement.")
        return uri, headers, body

    def _add_mac_token(self, uri, http_method=u'GET', body=None,
            headers=None, token_placement=AUTH_HEADER):
        """Add a MAC token to the request authorization header.

        Warning: MAC token support is experimental as the spec is not yet stable.
        """
        headers = prepare_mac_header(self.access_token, uri, self.key, http_method,
                        headers=headers, body=body, ext=self.ext,
                        hash_algorithm=self.hash_algorithm)
        return uri, headers, body

    def _populate_attributes(self, response):
        """Add commonly used values such as access_token to self."""

        if u'access_token' in response:
            self.access_token = response.get(u'access_token')

        if u'refresh_token' in response:
            self.refresh_token = response.get(u'refresh_token')

        if u'token_type' in response:
            self.token_type = response.get(u'token_type')

        if u'expires_in' in response:
            self.expires_in = response.get(u'expires_in')

        if u'code' in response:
            self.code = response.get(u'code')

    def prepare_request_uri(self, *args, **kwargs):
        """Abstract method used to create request URIs."""
        raise NotImplementedError("Must be implemented by inheriting classes.")

    def prepare_request_body(self, *args, **kwargs):
        """Abstract method used to create request bodies."""
        raise NotImplementedError("Must be implemented by inheriting classes.")

    def parse_request_uri_response(self, *args, **kwargs):
        """Abstract method used to parse redirection responses."""

    def parse_request_body_response(self, *args, **kwargs):
        """Abstract method used to parse JSON responses."""


class WebApplicationClient(Client):
    """A client utilizing the authorization code grant workflow.

    A web application is a confidential client running on a web
    server.  Resource owners access the client via an HTML user
    interface rendered in a user-agent on the device used by the
    resource owner.  The client credentials as well as any access
    token issued to the client are stored on the web server and are
    not exposed to or accessible by the resource owner.

    The authorization code grant type is used to obtain both access
    tokens and refresh tokens and is optimized for confidential clients.
    As a redirection-based flow, the client must be capable of
    interacting with the resource owner's user-agent (typically a web
    browser) and capable of receiving incoming requests (via redirection)
    from the authorization server.
    """

    def __init__(self, client_id, code=None, **kwargs):
        super(WebApplicationClient, self).__init__(client_id, **kwargs)
        if code:
            self.code = code

    def prepare_request_uri(self, uri, redirect_uri=None, scope=None,
            state=None, **kwargs):
        """Prepare the authorization code request URI

        The client constructs the request URI by adding the following
        parameters to the query component of the authorization endpoint URI
        using the "application/x-www-form-urlencoded" format as defined by
        [`W3C.REC-html401-19991224`_]:

        response_type
                REQUIRED.  Value MUST be set to "code".
        client_id
                REQUIRED.  The client identifier as described in `Section 2.2`_.
        redirect_uri
                OPTIONAL.  As described in `Section 3.1.2`_.
        scope
                OPTIONAL.  The scope of the access request as described by
                `Section 3.3`_.
        state
                RECOMMENDED.  An opaque value used by the client to maintain
                state between the request and callback.  The authorization
                server includes this value when redirecting the user-agent back
                to the client.  The parameter SHOULD be used for preventing
                cross-site request forgery as described in `Section 10.12`_.

        .. _`W3C.REC-html401-19991224`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#ref-W3C.REC-html401-19991224
        .. _`Section 2.2`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#section-2.2
        .. _`Section 3.1.2`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#section-3.1.2
        .. _`Section 3.3`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#section-3.3
        .. _`Section 10.12`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#section-10.12
        """
        return prepare_grant_uri(uri, self.client_id, u'code',
                redirect_uri=redirect_uri, scope=scope, state=state, **kwargs)

    def prepare_request_body(self, code=None, body=u'', redirect_uri=None, **kwargs):
        """Prepare the access token request body.

        The client makes a request to the token endpoint by adding the
        following parameters using the "application/x-www-form-urlencoded"
        format in the HTTP request entity-body:

        grant_type
                REQUIRED.  Value MUST be set to "authorization_code".
        code
                REQUIRED.  The authorization code received from the
                authorization server.
        redirect_uri
                REQUIRED, if the "redirect_uri" parameter was included in the
                authorization request as described in Section 4.1.1, and their
                values MUST be identical.

        .. _`Section 4.1.1`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#section-4.1.1
        """
        code = code or self.code
        return prepare_token_request(u'authorization_code', code=code, body=body,
                                          redirect_uri=redirect_uri, **kwargs)

    def parse_request_uri_response(self, uri, state=None):
        """Parse the URI query for code and state.

        If the resource owner grants the access request, the authorization
        server issues an authorization code and delivers it to the client by
        adding the following parameters to the query component of the
        redirection URI using the "application/x-www-form-urlencoded" format:

        code
                REQUIRED.  The authorization code generated by the
                authorization server.  The authorization code MUST expire
                shortly after it is issued to mitigate the risk of leaks.  A
                maximum authorization code lifetime of 10 minutes is
                RECOMMENDED.  The client MUST NOT use the authorization code
                more than once.  If an authorization code is used more than
                once, the authorization server MUST deny the request and SHOULD
                revoke (when possible) all tokens previously issued based on
                that authorization code.  The authorization code is bound to
                the client identifier and redirection URI.
        state
                REQUIRED if the "state" parameter was present in the client
                authorization request.  The exact value received from the
                client.
        """
        response = parse_authorization_code_response(uri, state=state)
        self._populate_attributes(response)
        return response

    def parse_request_body_response(self, body, scope=None):
        """Parse the JSON response body.

        If the access token request is valid and authorized, the
        authorization server issues an access token and optional refresh
        token as described in `Section 5.1`_.  If the request client
        authentication failed or is invalid, the authorization server returns
        an error response as described in `Section 5.2`_.

        .. `Section 5.1`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#section-5.1
        .. `Section 5.2`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#section-5.2
        """
        response = parse_token_response(body, scope=scope)
        self._populate_attributes(response)
        return response


class UserAgentClient(Client):
    """A public client utilizing the implicit code grant workflow.

    A user-agent-based application is a public client in which the
    client code is downloaded from a web server and executes within a
    user-agent (e.g. web browser) on the device used by the resource
    owner.  Protocol data and credentials are easily accessible (and
    often visible) to the resource owner.  Since such applications
    reside within the user-agent, they can make seamless use of the
    user-agent capabilities when requesting authorization.

    The implicit grant type is used to obtain access tokens (it does not
    support the issuance of refresh tokens) and is optimized for public
    clients known to operate a particular redirection URI.  These clients
    are typically implemented in a browser using a scripting language
    such as JavaScript.

    As a redirection-based flow, the client must be capable of
    interacting with the resource owner's user-agent (typically a web
    browser) and capable of receiving incoming requests (via redirection)
    from the authorization server.

    Unlike the authorization code grant type in which the client makes
    separate requests for authorization and access token, the client
    receives the access token as the result of the authorization request.

    The implicit grant type does not include client authentication, and
    relies on the presence of the resource owner and the registration of
    the redirection URI.  Because the access token is encoded into the
    redirection URI, it may be exposed to the resource owner and other
    applications residing on the same device.
    """

    def prepare_request_uri(self, uri, redirect_uri=None, scope=None,
            state=None, **kwargs):
        """Prepare the implicit grant request URI.

        The client constructs the request URI by adding the following
        parameters to the query component of the authorization endpoint URI
        using the "application/x-www-form-urlencoded" format:

        response_type
                REQUIRED.  Value MUST be set to "token".
        client_id
                REQUIRED.  The client identifier as described in Section 2.2.
        redirect_uri
                OPTIONAL.  As described in Section 3.1.2.
        scope
                OPTIONAL.  The scope of the access request as described by
                Section 3.3.
        state
                RECOMMENDED.  An opaque value used by the client to maintain
                state between the request and callback.  The authorization
                server includes this value when redirecting the user-agent back
                to the client.  The parameter SHOULD be used for preventing
                cross-site request forgery as described in Section 10.12.
        """
        return prepare_grant_uri(uri, self.client_id, u'token',
                redirect_uri=redirect_uri, state=state, scope=scope, **kwargs)

    def parse_request_uri_response(self, uri, state=None, scope=None):
        """Parse the response URI fragment.

        If the resource owner grants the access request, the authorization
        server issues an access token and delivers it to the client by adding
        the following parameters to the fragment component of the redirection
        URI using the "application/x-www-form-urlencoded" format:

        access_token
                REQUIRED.  The access token issued by the authorization server.
        token_type
                REQUIRED.  The type of the token issued as described in
                `Section 7.1`_.  Value is case insensitive.
        expires_in
                RECOMMENDED.  The lifetime in seconds of the access token.  For
                example, the value "3600" denotes that the access token will
                expire in one hour from the time the response was generated.
                If omitted, the authorization server SHOULD provide the
                expiration time via other means or document the default value.
        scope
                OPTIONAL, if identical to the scope requested by the client,
                otherwise REQUIRED.  The scope of the access token as described
                by `Section 3.3`_.
        state
                REQUIRED if the "state" parameter was present in the client
                authorization request.  The exact value received from the
                client.

        .. _`Section 7.1`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#section-7.1
        .. _`Section 3.3`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#section-3.3
        """
        response = parse_implicit_response(uri, state=state, scope=scope)
        self._populate_attributes(response)
        return response


class ClientCredentialsClient(Client):
    """A public client utilizing the client credentials grant workflow.

    The client can request an access token using only its client
    credentials (or other supported means of authentication) when the
    client is requesting access to the protected resources under its
    control, or those of another resource owner which has been previously
    arranged with the authorization server (the method of which is beyond
    the scope of this specification).

    The client credentials grant type MUST only be used by confidential
    clients.

    Since the client authentication is used as the authorization grant,
    no additional authorization request is needed.
    """

    def prepare_request_body(self, body=u'', scope=None, **kwargs):
        """Add the client credentials to the request body.

        The client makes a request to the token endpoint by adding the
        following parameters using the "application/x-www-form-urlencoded"
        format in the HTTP request entity-body:

        grant_type
                REQUIRED.  Value MUST be set to "client_credentials".
        scope
                OPTIONAL.  The scope of the access request as described by
                `Section 3.3`_.

        .. _`Section 3.3`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#section-3.3
        """
        return prepare_token_request(u'client_credentials', body=body,
                                     scope=scope, **kwargs)

    def parse_request_body_response(self, body, scope=None):
        """Parse the JSON response body.

        If the access token request is valid and authorized, the
        authorization server issues an access token as described in
        `Section 5.1`_.  A refresh token SHOULD NOT be included.  If the request
        failed client authentication or is invalid, the authorization server
        returns an error response as described in `Section 5.2`_.

        .. `Section 5.1`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#section-5.1
        .. `Section 5.2`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#section-5.2
        """
        response = parse_token_response(body, scope=scope)
        self._populate_attributes(response)
        return response


class PasswordCredentialsClient(Client):
    """A public client using the resource owner password and username directly.

    The resource owner password credentials grant type is suitable in
    cases where the resource owner has a trust relationship with the
    client, such as the device operating system or a highly privileged
    application.  The authorization server should take special care when
    enabling this grant type, and only allow it when other flows are not
    viable.

    The grant type is suitable for clients capable of obtaining the
    resource owner's credentials (username and password, typically using
    an interactive form).  It is also used to migrate existing clients
    using direct authentication schemes such as HTTP Basic or Digest
    authentication to OAuth by converting the stored credentials to an
    access token.

    The method through which the client obtains the resource owner
    credentials is beyond the scope of this specification.  The client
    MUST discard the credentials once an access token has been obtained.
    """

    def __init__(self, client_id, username, password, **kwargs):
        super(PasswordCredentialsClient, self).__init__(client_id, **kwargs)
        self.username = username
        self.password = password

    def prepare_request_body(self, body=u'', scope=None, **kwargs):
        """Add the resource owner password and username to the request body.

        The client makes a request to the token endpoint by adding the
        following parameters using the "application/x-www-form-urlencoded"
        format in the HTTP request entity-body:

        grant_type
                REQUIRED.  Value MUST be set to "password".
        username
                REQUIRED.  The resource owner username.
        password
                REQUIRED.  The resource owner password.
        scope
                OPTIONAL.  The scope of the access request as described by
                `Section 3.3`_.

        .. _`Section 3.3`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#section-3.3
        """
        return prepare_token_request(u'password', body=body, username=self.username,
                password=self.password, scope=scope, **kwargs)

    def parse_request_body_response(self, body, scope=None):
        """Parse the JSON response body.

        If the access token request is valid and authorized, the
        authorization server issues an access token and optional refresh
        token as described in `Section 5.1`_.  If the request failed client
        authentication or is invalid, the authorization server returns an
        error response as described in `Section 5.2`_.

        .. `Section 5.1`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#section-5.1
        .. `Section 5.2`: http://tools.ietf.org/html/draft-ietf-oauth-v2-28#section-5.2
        """
        response = parse_token_response(body, scope=scope)
        self._populate_attributes(response)
        return response


class OAuth2Error(Exception):
# TODO: move into error.py

    def __init__(self, description=None, uri=None, state=None):
        """
        description:    A human-readable ASCII [USASCII] text providing
                        additional information, used to assist the client
                        developer in understanding the error that occurred.
                        Values for the "error_description" parameter MUST NOT
                        include characters outside the set
                        %x20-21 / %x23-5B / %x5D-7E.

        uri:    A URI identifying a human-readable web page with information
                about the error, used to provide the client developer with
                additional information about the error.  Values for the
                "error_uri" parameter MUST conform to the URI- Reference
                syntax, and thus MUST NOT include characters outside the set
                %x21 / %x23-5B / %x5D-7E.

        state:  A CSRF protection value received from the client.
        """
        self.description = description
        self.uri = uri
        self.state = state

    @property
    def twotuples(self):
        error = [(u'error', self.error)]
        if self.description:
            error.append((u'error_description', self.description))
        if self.uri:
            error.append((u'error_uri', self.uri))
        if self.state:
            error.append((u'state', self.state))
        return error

    @property
    def urlencoded(self):
        pass

    @property
    def json(self):
        pass


class AuthorizationEndpoint(object):
    """Authorization endpoint - used by the client to obtain authorization
    from the resource owner via user-agent redirection.

    The authorization endpoint is used to interact with the resource
    owner and obtain an authorization grant.  The authorization server
    MUST first verify the identity of the resource owner.  The way in
    which the authorization server authenticates the resource owner (e.g.
    username and password login, session cookies) is beyond the scope of
    this specification.

    The endpoint URI MAY include an "application/x-www-form-urlencoded"
    formatted (per Appendix B) query component ([RFC3986] section 3.4),
    which MUST be retained when adding additional query parameters.  The
    endpoint URI MUST NOT include a fragment component.

    Since requests to the authorization endpoint result in user
    authentication and the transmission of clear-text credentials (in the
    HTTP response), the authorization server MUST require the use of TLS
    as described in Section 1.6 when sending requests to the
    authorization endpoint.

    The authorization server MUST support the use of the HTTP "GET"
    method [RFC2616] for the authorization endpoint, and MAY support the
    use of the "POST" method as well.

    Parameters sent without a value MUST be treated as if they were
    omitted from the request.  The authorization server MUST ignore
    unrecognized request parameters.  Request and response parameters
    MUST NOT be included more than once.
    """

    class InvalidRequestError(OAuth2Error):
        """The request is missing a required parameter, includes an invalid
        parameter value, includes a parameter more than once, or is
        otherwise malformed.
        """
        error = u'invalid_request'

    class UnauthorizedClientError(OAuth2Error):
        """The client is not authorized to request an authorization code using
        this method.
        """
        error = u'unauthorized_client'

    class AccessDeniedError(OAuth2Error):
        """The resource owner or authorization server denied the request."""
        error = u'access_denied'

    class UnsupportedResponseTypeError(OAuth2Error):
        """The authorization server does not support obtaining an authorization
        code using this method.
        """
        error = u'unsupported_response_type'

    class InvalidScopeError(OAuth2Error):
        """The requested scope is invalid, unknown, or malformed."""
        error = u'invalid_scope'

    class ServerError(OAuth2Error):
        """The authorization server encountered an unexpected condition that
        prevented it from fulfilling the request.  (This error code is needed
        because a 500 Internal Server Error HTTP status code cannot be returned
        to the client via a HTTP redirect.)
        """
        error = u'server_error'

    class TemporarilyUnvailableError(OAuth2Error):
        """The authorization server is currently unable to handle the request
        due to a temporary overloading or maintenance of the server.
        (This error code is needed because a 503 Service Unavailable HTTP
        status code cannot be returned to the client via a HTTP redirect.)
        """
        error = u'temporarily_unavailable'

    def __init__(self, valid_scopes=None):
        self.valid_scopes = valid_scopes
        self.state = None

    @property
    def response_type_handlers(self):
        return {
            u'code': AuthorizationGrantCodeHandler(),
            u'token': ImplicitGrantHandler(),
        }

    def parse_authorization_parameters(self, uri):
        self.params = params_from_uri(uri)
        self.client_id = self.params.get(u'client_id', None)
        self.scopes = self.params.get(u'scope', None)
        self.redirect_uri = self.params.get(u'redirect_uri', None)
        self.response_type = self.params.get(u'response_type')
        self.state = self.params.get(u'state')
        self.validate_authorization_parameters()

    def validate_authorization_parameters(self):

        if not self.client_id:
            raise AuthorizationEndpoint.InvalidRequestError(state=self.state,
                    description=u'Missing client_id parameter.')

        if not self.response_type:
            raise AuthorizationEndpoint.InvalidRequestError(state=self.state,
                    description=u'Missing response_type parameter.')

        if not self.validate_client(self.client_id):
            raise AuthorizationEndpoint.UnauthorizedClientError(state=self.state)

        if not self.response_type in self.response_type_handlers:
            raise AuthorizationEndpoint.UnsupportedResponseTypeError(state=self.state)

        if self.scopes:
            if not self.validate_scopes(self.client_id, self.scopes):
                raise AuthorizationEndpoint.InvalidScopeError(state=self.state)
        else:
            self.scopes = self.get_default_scopes(self.client_id)

        if self.redirect_uri:
            if not is_absolute_uri(self.redirect_uri):
                raise AuthorizationEndpoint.InvalidRequestError(state=self.state,
                        description=u'Non absolute redirect URI. See RFC3986')

            if not self.validate_redirect_uri(self.client_id, self.redirect_uri):
                raise AuthorizationEndpoint.AccessDeniedError(state=self.state)
        else:
            self.redirect_uri = self.get_default_redirect_uri(self.client_id)
            if not self.redirect_uri:
                raise AuthorizationEndpoint.AccessDeniedError(state=self.state)

        return True

    def create_authorization_response(self, authorized_scopes):
        self.scopes = authorized_scopes

        if not self.response_type in self.response_type_handlers:
            raise AuthorizationEndpoint.UnsupportedResponseTypeError(
                    state=self.state, description=u'Invalid response type')

        return self.response_type_handlers.get(self.response_type)(self)

    def validate_client(self, client_id):
        raise NotImplementedError('Subclasses must implement this method.')

    def validate_scopes(self, client_id, scopes):
        raise NotImplementedError('Subclasses must implement this method.')

    def validate_redirect_uri(self, client_id, redirect_uri):
        raise NotImplementedError('Subclasses must implement this method.')

    def get_default_redirect_uri(self, client_id):
        raise NotImplementedError('Subclasses must implement this method.')

    def get_default_scopes(self, client_id):
        raise NotImplementedError('Subclasses must implement this method.')

    def save_authorization_grant(self, client_id, grant, state=None):
        """Saves authorization codes for later use by the token endpoint.

        code:   The authorization code generated by the authorization server.
                The authorization code MUST expire shortly after it is issued
                to mitigate the risk of leaks. A maximum authorization code
                lifetime of 10 minutes is RECOMMENDED.

        state:  A CSRF protection value received from the client.
        """
        raise NotImplementedError('Subclasses must implement this method.')

    def save_implicit_grant(self, client_id, grant, state=None):
        raise NotImplementedError('Subclasses must implement this method.')


def params_from_uri(uri):
    import urlparse
    query = urlparse.urlparse(uri).query
    params = dict(urlparse.parse_qsl(query))
    if u'scope' in params:
        params[u'scope'] = params[u'scope'].split(u' ')
    return params


class AuthorizationGrantCodeHandler(object):

    def __call__(self, endpoint):
        self.endpoint = endpoint
        try:
            self.endpoint.validate_authorization_parameters()

        except OAuth2Error as e:
            return add_params_to_uri(self.endpoint.redirect_uri, e.twotuples)

        self.grant = self.create_authorization_grant()
        self.endpoint.save_authorization_grant(
                self.endpoint.client_id, self.grant, state=self.endpoint.state)
        return add_params_to_uri(self.endpoint.redirect_uri, self.grant.items())

    def create_authorization_grant(self):
        """Generates an authorization grant represented as a dictionary."""
        grant = {u'code': generate_token()}
        if self.endpoint.state:
            grant[u'state'] = self.endpoint.state
        return grant


class ImplicitGrantHandler(object):

    @property
    def expires_in(self):
        return 3600

    @property
    def token_type(self):
        return u'Bearer'

    def create_implicit_grant(self):
        return {
            u'access_token': generate_token(),
            u'token_type': self.token_type,
            u'expires_in': self.expires_in,
            u'scope': ' '.join(self.endpoint.scopes),
            u'state': self.endpoint.state
        }

    def __call__(self, endpoint):
        self.endpoint = endpoint
        try:
            self.endpoint.validate_authorization_parameters()

        except OAuth2Error as e:
            return add_params_to_uri(
                    self.endpoint.redirect_uri, e.twotuples, fragment=True)

        self.grant = self.create_implicit_grant()
        self.endpoint.save_implicit_grant(
                self.endpoint.client_id, self.grant, state=self.endpoint.state)
        return add_params_to_uri(
                self.endpoint.redirect_uri, self.grant.items(), fragment=True)


class TokenEndpoint(object):

    def access_token(self, uri, body, http_method=u'GET', headers=None):
        """Validate client, code etc, return body + headers"""
        pass

    def validate_authorization_code(self, client_id):
        """Validate the authorization code.

        The client MUST NOT use the authorization code more than once. If an
        authorization code is used more than once, the authorization server
        MUST deny the request and SHOULD revoke (when possible) all tokens
        previously issued based on that authorization code. The authorization
        code is bound to the client identifier and redirection URI.
        """
        pass


class ResourceEndpoint(object):
    pass


class Server(AuthorizationEndpoint, TokenEndpoint, ResourceEndpoint):
    pass
