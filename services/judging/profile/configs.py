from __future__ import annotations

from dataclasses import dataclass

from utils.ids import MAIN_CHANNELS, MAIN_ROLES, JUDGE_TAGS


@dataclass(frozen=True)
class ProfileJudgingChannels:
    judge_channel_id: int = MAIN_CHANNELS.PROFILE_JUDGE
    result_forum_id: int = MAIN_CHANNELS.PROFILE_JUDGE_RESULT


@dataclass(frozen=True)
class ProfileJudgingMentionRoles:
    member_role_id: int = MAIN_ROLES.MEMBER
    probation_member_role_id: int = MAIN_ROLES.P_MEMBER


@dataclass(frozen=True)
class ProfileJudgingGenderRoles:
    male_role_id: int = MAIN_ROLES.G_MALE
    female_role_id: int = MAIN_ROLES.G_FEMALE


@dataclass(frozen=True)
class ProfileJudgingTags:
    now_tag_id: int = JUDGE_TAGS.NOW
    male_tag_id: int = JUDGE_TAGS.MALE
    female_tag_id: int = JUDGE_TAGS.FEMALE


@dataclass(frozen=True)
class ProfileJudgingConfig:
    channels: ProfileJudgingChannels = ProfileJudgingChannels()
    mention_roles: ProfileJudgingMentionRoles = ProfileJudgingMentionRoles()
    gender_roles: ProfileJudgingGenderRoles = ProfileJudgingGenderRoles()
    tags: ProfileJudgingTags = ProfileJudgingTags()


PROFILE_JUDGING_CONFIG = ProfileJudgingConfig()