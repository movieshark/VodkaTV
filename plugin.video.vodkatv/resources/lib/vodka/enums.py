from enum import Enum


class LoginStatusCodes(Enum):
    OK = 0
    UserExists = 1
    UserDoesNotExist = 2
    WrongPasswordOrUserName = 3
    InsideLockTime = 4
    NotImplementedYet = 5
    UserNotActivated = 6
    UserAllreadyLoggedIn = 7
    UserDoubleLogIn = 8
    SessionLoggedOut = 9
    DeviceNotRegistered = 10
    ErrorOnSendingMail = 11
    UserEmailAlreadyExists = 12
    ErrorOnUpdatingUserType = 13
    UserTypeNotExist = 14
    UserNotMasterApproved = 15
    ErrorOnInitUser = 16
    ErrorOnSaveUser = 17
    UserNotIndDomain = 18
    TokenNotFound = 19
    UserAlreadyMasterApproved = 20
    UserWithNoDomain = 21
    InternalError = 22
    LoginServerDown = 23
    UserSuspended = 24
    # encountered this while testing
    # it's not documented in the API
    UnknownBackendError999 = 999


class DeviceBrandId(Enum):
    iPhone = 1
    SamsungGalaxyS = 2
    iPad = 3
    SamsungGalaxyTab = 4
    PeerTV = 5
    Boxee = 8
    Samsung = 9
    HTC = 11
    Blackberry = 12
    Netgem = 13
    Roku = 14
    YouView = 15
    MotorolaXoom = 21
    PCMAC = 22
    PCMACApplication = 23
    XBox = 24
    Playstation3 = 25
    Wii = 26
    T20 = 28
    Zappaware = 29
    Oregan = 30
    AndroidTablet = 31
    AndroidSmartphone = 32
    ABox42 = 33
    Kaon = 34
    TIVO = 35
    AmazonFireTvLowEnd = 36
    AmazonFireTvMidEnd = 37
    Vestel = 6
    Vantage = 7
    Toshiba = 10
    LGTV = 16
    PanasonicTV = 17
    PhillipsTV = 18
    SonyTV = 19
    SamsungTV = 20
    GoogleTV = 27
    HiSenseTV = 38
    Blaupunkt = 200
    Kunft = 201
    Kubo = 202
    Loewe = 203
    Sharp = 204
    TCL = 205
    AOC = 206
    Skyworth = 207
    Haier = 208
    Vizio = 209
    Thomson = 210
    Changhong = 211
    Other = 212
    Xiaomi = 328
    Toshiba_STV = 300
    LG_STV = 301
    Panasonic_STV = 302
    Sony_STV = 303
    Samsung_STV = 304
    Hisense_STV = 305
    Blaupunkt_STV = 306
    Kunft_STV = 307
    Kubo_STV = 308
    Loewe_STV = 309
    Sharp_STV = 310
    TCL_STV = 311
    AOC_STV = 312
    Skyworth_STV = 313
    Haier_STV = 314
    Vizio_STV = 315
    Thomson_STV = 316
    Changhong_STV = 317
    Other_STV = 318
    Philips_STV = 321
    Xiaomi_STV = 329
    # different from what the API returns
    # but similar values are baked in the apps
    # use it for login only, API is more reliable


class DomainResponseStatus(Enum):
    LimitationPeriod = 0
    UnKnown = 1
    Error = 2
    DomainAlreadyExists = 3
    ExceededLimit = 4
    DeviceTypeNotAllowed = 5
    DeviceNotInDomain = 6
    DeviceNotExists = 7
    DeviceAlreadyExists = 8
    UserNotExistsInDomain = 9
    OK = 10
    ActionUserNotMaster = 11
    UserNotAllowed = 12
    ExceededUserLimit = 13
    NoUsersInDomain = 14
    UserExistsInOtherDomains = 15
    DomainNotExists = 16
    HouseholdUserFailed = 17
    DeviceExistsInOtherDomains = 18
    DomainNotInitialized = 19
    RequestSent = 20
    DeviceNotConfirmed = 21
    RequestFailed = 22
    InvalidUser = 23
    ConcurrencyLimitation = 24
    MediaConcurrencyLimitation = 25
    DomainSuspended = 26
    UserAlreadyInDomain = 27
