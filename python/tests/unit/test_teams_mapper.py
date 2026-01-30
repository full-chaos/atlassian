import pytest

from atlassian.canonical_models import AtlassianTeam, AtlassianTeamMember
from atlassian.graph.mappers.teams import map_team, map_team_member


class TestMapTeam:
    """Tests for map_team() function."""

    def test_map_team_with_required_fields_only(self):
        """Test mapping team with only required fields."""
        team = type(
            "Team",
            (),
            {
                "id": "ari:cloud:identity::team/abc123",
                "display_name": "Engineering",
                "state": "ACTIVE",
            },
        )()

        result = map_team(team)

        assert isinstance(result, AtlassianTeam)
        assert result.id == "ari:cloud:identity::team/abc123"
        assert result.display_name == "Engineering"
        assert result.state == "ACTIVE"
        assert result.description is None
        assert result.avatar_url is None
        assert result.member_count is None

    def test_map_team_with_all_fields(self):
        """Test mapping team with all fields populated."""
        team = type(
            "Team",
            (),
            {
                "id": "ari:cloud:identity::team/xyz789",
                "display_name": "Platform Team",
                "state": "ACTIVE",
                "description": "Responsible for platform infrastructure",
                "avatar_url": "https://example.com/avatar.png",
                "member_count": 5,
            },
        )()

        result = map_team(team)

        assert result.id == "ari:cloud:identity::team/xyz789"
        assert result.display_name == "Platform Team"
        assert result.state == "ACTIVE"
        assert result.description == "Responsible for platform infrastructure"
        assert result.avatar_url == "https://example.com/avatar.png"
        assert result.member_count == 5

    def test_map_team_trims_whitespace(self):
        """Test that required fields are trimmed."""
        team = type(
            "Team",
            (),
            {
                "id": "  ari:cloud:identity::team/abc123  ",
                "display_name": "  Engineering  ",
                "state": "  ACTIVE  ",
            },
        )()

        result = map_team(team)

        assert result.id == "ari:cloud:identity::team/abc123"
        assert result.display_name == "Engineering"
        assert result.state == "ACTIVE"

    def test_map_team_optional_fields_trimmed(self):
        """Test that optional string fields are trimmed."""
        team = type(
            "Team",
            (),
            {
                "id": "ari:cloud:identity::team/abc123",
                "display_name": "Engineering",
                "state": "ACTIVE",
                "description": "  A team  ",
                "avatar_url": "  https://example.com/avatar.png  ",
            },
        )()

        result = map_team(team)

        assert result.description == "A team"
        assert result.avatar_url == "https://example.com/avatar.png"

    def test_map_team_optional_fields_empty_string_becomes_none(self):
        """Test that empty/whitespace-only optional fields become None."""
        team = type(
            "Team",
            (),
            {
                "id": "ari:cloud:identity::team/abc123",
                "display_name": "Engineering",
                "state": "ACTIVE",
                "description": "   ",
                "avatar_url": "",
            },
        )()

        result = map_team(team)

        assert result.description is None
        assert result.avatar_url is None

    def test_map_team_member_count_valid_int(self):
        """Test that valid integer member_count is preserved."""
        team = type(
            "Team",
            (),
            {
                "id": "ari:cloud:identity::team/abc123",
                "display_name": "Engineering",
                "state": "ACTIVE",
                "member_count": 10,
            },
        )()

        result = map_team(team)

        assert result.member_count == 10

    def test_map_team_member_count_zero(self):
        """Test that zero member_count is preserved."""
        team = type(
            "Team",
            (),
            {
                "id": "ari:cloud:identity::team/abc123",
                "display_name": "Engineering",
                "state": "ACTIVE",
                "member_count": 0,
            },
        )()

        result = map_team(team)

        assert result.member_count == 0

    def test_map_team_member_count_non_int_becomes_none(self):
        """Test that non-integer member_count becomes None."""
        team = type(
            "Team",
            (),
            {
                "id": "ari:cloud:identity::team/abc123",
                "display_name": "Engineering",
                "state": "ACTIVE",
                "member_count": "10",  # string instead of int
            },
        )()

        result = map_team(team)

        assert result.member_count is None

    def test_map_team_member_count_bool_becomes_none(self):
        """Test that boolean member_count becomes None (not treated as int)."""
        team = type(
            "Team",
            (),
            {
                "id": "ari:cloud:identity::team/abc123",
                "display_name": "Engineering",
                "state": "ACTIVE",
                "member_count": True,
            },
        )()

        result = map_team(team)

        assert result.member_count is None

    def test_map_team_missing_id_raises_error(self):
        """Test that missing id raises ValueError."""
        team = type(
            "Team",
            (),
            {
                "display_name": "Engineering",
                "state": "ACTIVE",
            },
        )()

        with pytest.raises(ValueError, match="team.id is required"):
            map_team(team)

    def test_map_team_empty_id_raises_error(self):
        """Test that empty id raises ValueError."""
        team = type(
            "Team",
            (),
            {
                "id": "",
                "display_name": "Engineering",
                "state": "ACTIVE",
            },
        )()

        with pytest.raises(ValueError, match="team.id is required"):
            map_team(team)

    def test_map_team_whitespace_only_id_raises_error(self):
        """Test that whitespace-only id raises ValueError."""
        team = type(
            "Team",
            (),
            {
                "id": "   ",
                "display_name": "Engineering",
                "state": "ACTIVE",
            },
        )()

        with pytest.raises(ValueError, match="team.id is required"):
            map_team(team)

    def test_map_team_missing_display_name_raises_error(self):
        """Test that missing display_name raises ValueError."""
        team = type(
            "Team",
            (),
            {
                "id": "ari:cloud:identity::team/abc123",
                "state": "ACTIVE",
            },
        )()

        with pytest.raises(ValueError, match="team.displayName is required"):
            map_team(team)

    def test_map_team_empty_display_name_raises_error(self):
        """Test that empty display_name raises ValueError."""
        team = type(
            "Team",
            (),
            {
                "id": "ari:cloud:identity::team/abc123",
                "display_name": "",
                "state": "ACTIVE",
            },
        )()

        with pytest.raises(ValueError, match="team.displayName is required"):
            map_team(team)

    def test_map_team_missing_state_raises_error(self):
        """Test that missing state raises ValueError."""
        team = type(
            "Team",
            (),
            {
                "id": "ari:cloud:identity::team/abc123",
                "display_name": "Engineering",
            },
        )()

        with pytest.raises(ValueError, match="team.state is required"):
            map_team(team)

    def test_map_team_empty_state_raises_error(self):
        """Test that empty state raises ValueError."""
        team = type(
            "Team",
            (),
            {
                "id": "ari:cloud:identity::team/abc123",
                "display_name": "Engineering",
                "state": "",
            },
        )()

        with pytest.raises(ValueError, match="team.state is required"):
            map_team(team)

    def test_map_team_none_input_raises_error(self):
        """Test that None input raises ValueError."""
        with pytest.raises(ValueError, match="team is required"):
            map_team(None)

    def test_map_team_non_string_id_raises_error(self):
        """Test that non-string id raises ValueError."""
        team = type(
            "Team",
            (),
            {
                "id": 123,
                "display_name": "Engineering",
                "state": "ACTIVE",
            },
        )()

        with pytest.raises(ValueError, match="team.id is required"):
            map_team(team)

    def test_map_team_non_string_display_name_raises_error(self):
        """Test that non-string display_name raises ValueError."""
        team = type(
            "Team",
            (),
            {
                "id": "ari:cloud:identity::team/abc123",
                "display_name": 123,
                "state": "ACTIVE",
            },
        )()

        with pytest.raises(ValueError, match="team.displayName is required"):
            map_team(team)

    def test_map_team_non_string_state_raises_error(self):
        """Test that non-string state raises ValueError."""
        team = type(
            "Team",
            (),
            {
                "id": "ari:cloud:identity::team/abc123",
                "display_name": "Engineering",
                "state": 123,
            },
        )()

        with pytest.raises(ValueError, match="team.state is required"):
            map_team(team)


class TestMapTeamMember:
    """Tests for map_team_member() function."""

    def test_map_team_member_with_required_fields_only(self):
        """Test mapping team member with only required fields."""
        member = type(
            "Member",
            (),
            {
                "account_id": "user123",
            },
        )()

        result = map_team_member(team_id="team-abc", member=member)

        assert isinstance(result, AtlassianTeamMember)
        assert result.team_id == "team-abc"
        assert result.account_id == "user123"
        assert result.display_name is None
        assert result.role is None

    def test_map_team_member_with_all_fields(self):
        """Test mapping team member with all fields populated."""
        member = type(
            "Member",
            (),
            {
                "account_id": "user456",
                "display_name": "Alice Smith",
                "role": "ADMIN",
            },
        )()

        result = map_team_member(team_id="team-xyz", member=member)

        assert result.team_id == "team-xyz"
        assert result.account_id == "user456"
        assert result.display_name == "Alice Smith"
        assert result.role == "ADMIN"

    def test_map_team_member_trims_whitespace(self):
        """Test that required fields are trimmed."""
        member = type(
            "Member",
            (),
            {
                "account_id": "  user123  ",
            },
        )()

        result = map_team_member(team_id="  team-abc  ", member=member)

        assert result.team_id == "team-abc"
        assert result.account_id == "user123"

    def test_map_team_member_optional_fields_trimmed(self):
        """Test that optional string fields are trimmed."""
        member = type(
            "Member",
            (),
            {
                "account_id": "user123",
                "display_name": "  Alice Smith  ",
                "role": "  ADMIN  ",
            },
        )()

        result = map_team_member(team_id="team-abc", member=member)

        assert result.display_name == "Alice Smith"
        assert result.role == "ADMIN"

    def test_map_team_member_optional_fields_empty_string_becomes_none(self):
        """Test that empty/whitespace-only optional fields become None."""
        member = type(
            "Member",
            (),
            {
                "account_id": "user123",
                "display_name": "   ",
                "role": "",
            },
        )()

        result = map_team_member(team_id="team-abc", member=member)

        assert result.display_name is None
        assert result.role is None

    def test_map_team_member_missing_account_id_raises_error(self):
        """Test that missing account_id raises ValueError."""
        member = type("Member", (), {})()

        with pytest.raises(ValueError, match="member.accountId is required"):
            map_team_member(team_id="team-abc", member=member)

    def test_map_team_member_empty_account_id_raises_error(self):
        """Test that empty account_id raises ValueError."""
        member = type(
            "Member",
            (),
            {
                "account_id": "",
            },
        )()

        with pytest.raises(ValueError, match="member.accountId is required"):
            map_team_member(team_id="team-abc", member=member)

    def test_map_team_member_whitespace_only_account_id_raises_error(self):
        """Test that whitespace-only account_id raises ValueError."""
        member = type(
            "Member",
            (),
            {
                "account_id": "   ",
            },
        )()

        with pytest.raises(ValueError, match="member.accountId is required"):
            map_team_member(team_id="team-abc", member=member)

    def test_map_team_member_missing_team_id_raises_error(self):
        """Test that missing team_id raises ValueError."""
        member = type(
            "Member",
            (),
            {
                "account_id": "user123",
            },
        )()

        with pytest.raises(ValueError, match="teamId is required"):
            map_team_member(team_id="", member=member)

    def test_map_team_member_whitespace_only_team_id_raises_error(self):
        """Test that whitespace-only team_id raises ValueError."""
        member = type(
            "Member",
            (),
            {
                "account_id": "user123",
            },
        )()

        with pytest.raises(ValueError, match="teamId is required"):
            map_team_member(team_id="   ", member=member)

    def test_map_team_member_none_member_raises_error(self):
        """Test that None member raises ValueError."""
        with pytest.raises(ValueError, match="member is required"):
            map_team_member(team_id="team-abc", member=None)

    def test_map_team_member_non_string_account_id_raises_error(self):
        """Test that non-string account_id raises ValueError."""
        member = type(
            "Member",
            (),
            {
                "account_id": 123,
            },
        )()

        with pytest.raises(ValueError, match="member.accountId is required"):
            map_team_member(team_id="team-abc", member=member)

    def test_map_team_member_non_string_team_id_raises_error(self):
        """Test that non-string team_id raises ValueError."""
        member = type(
            "Member",
            (),
            {
                "account_id": "user123",
            },
        )()

        with pytest.raises(ValueError, match="teamId is required"):
            map_team_member(team_id=123, member=member)

    def test_map_team_member_non_string_display_name_becomes_none(self):
        """Test that non-string display_name becomes None."""
        member = type(
            "Member",
            (),
            {
                "account_id": "user123",
                "display_name": 123,
            },
        )()

        result = map_team_member(team_id="team-abc", member=member)

        assert result.display_name is None

    def test_map_team_member_non_string_role_becomes_none(self):
        """Test that non-string role becomes None."""
        member = type(
            "Member",
            (),
            {
                "account_id": "user123",
                "role": 123,
            },
        )()

        result = map_team_member(team_id="team-abc", member=member)

        assert result.role is None
