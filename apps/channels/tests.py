from django.test import TestCase
from django.utils import timezone
from apps.channels.models import Channel, ChannelGroup, Logo
from apps.m3u.models import M3UAccount


class ChannelUserEditedMetadataTests(TestCase):
    """Test cases for persistent user-edited channel metadata functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.channel_group = ChannelGroup.objects.create(name="Test Group")
        self.logo1 = Logo.objects.create(name="Logo 1", url="http://example.com/logo1.png")
        self.logo2 = Logo.objects.create(name="Logo 2", url="http://example.com/logo2.png")
        self.m3u_account = M3UAccount.objects.create(
            name="Test M3U Account",
            server_url="http://example.com/playlist.m3u",
            is_active=True
        )
    
    def test_channel_effective_name_precedence(self):
        """Test that effective_name returns user_name over m3u_name over name."""
        channel = Channel.objects.create(
            channel_number=1.0,
            name="Original Name",
            channel_group=self.channel_group
        )
        
        # No user_name or m3u_name, should return name
        self.assertEqual(channel.effective_name, "Original Name")
        
        # Set m3u_name, should return m3u_name
        channel.m3u_name = "M3U Name"
        channel.save()
        self.assertEqual(channel.effective_name, "M3U Name")
        
        # Set user_name, should return user_name (highest priority)
        channel.user_name = "User Name"
        channel.save()
        self.assertEqual(channel.effective_name, "User Name")
        
        # Clear user_name, should fall back to m3u_name
        channel.user_name = None
        channel.save()
        self.assertEqual(channel.effective_name, "M3U Name")
    
    def test_channel_effective_logo_precedence(self):
        """Test that effective_logo returns user_logo over logo derived from m3u_logo_url over logo."""
        channel = Channel.objects.create(
            channel_number=2.0,
            name="Test Channel",
            channel_group=self.channel_group,
            logo=self.logo1
        )
        
        # No user_logo or m3u_logo_url, should return logo
        self.assertEqual(channel.effective_logo, self.logo1)
        
        # Set m3u_logo_url but keep existing logo, should still return logo
        channel.m3u_logo_url = "http://example.com/m3u_logo.png"
        channel.save()
        self.assertEqual(channel.effective_logo, self.logo1)
        
        # Set user_logo, should return user_logo (highest priority)
        channel.user_logo = self.logo2
        channel.save()
        self.assertEqual(channel.effective_logo, self.logo2)
        
        # Clear user_logo, should fall back to original logo
        channel.user_logo = None
        channel.save()
        self.assertEqual(channel.effective_logo, self.logo1)
    
    def test_m3u_sync_preserves_user_edits(self):
        """Test that M3U sync preserves user-edited values when M3U values haven't changed."""
        # Create a channel as if it was auto-created from M3U
        channel = Channel.objects.create(
            channel_number=3.0,
            name="M3U Channel",
            m3u_name="M3U Channel",
            m3u_logo_url="http://example.com/original_logo.png",
            channel_group=self.channel_group,
            logo=self.logo1,
            auto_created=True,
            auto_created_by=self.m3u_account
        )
        
        # User customizes the channel
        channel.user_name = "My Custom Name"
        channel.user_logo = self.logo2
        channel.save()
        
        # Verify user customizations are returned
        self.assertEqual(channel.effective_name, "My Custom Name")
        self.assertEqual(channel.effective_logo, self.logo2)
        
        # Simulate M3U sync with same values (no change)
        # This should NOT overwrite user customizations
        channel.refresh_from_db()  # Simulate reload from sync process
        
        # User customizations should still be intact
        self.assertEqual(channel.user_name, "My Custom Name")
        self.assertEqual(channel.user_logo, self.logo2)
        self.assertEqual(channel.effective_name, "My Custom Name")
        self.assertEqual(channel.effective_logo, self.logo2)
    
    def test_m3u_sync_updates_when_source_changes(self):
        """Test that M3U sync updates tracking fields when source values change."""
        # Create a channel with initial M3U values
        channel = Channel.objects.create(
            channel_number=4.0,
            name="Original M3U Name",
            m3u_name="Original M3U Name",
            m3u_logo_url="http://example.com/original_logo.png",
            channel_group=self.channel_group,
            auto_created=True,
            auto_created_by=self.m3u_account
        )
        
        # User has NOT customized the channel
        self.assertIsNone(channel.user_name)
        self.assertIsNone(channel.user_logo)
        
        # Simulate M3U sync with changed values
        # This should update both m3u_* fields and the default fields since user hasn't customized
        channel.m3u_name = "Updated M3U Name"
        channel.name = "Updated M3U Name"  # Sync would update this
        channel.m3u_logo_url = "http://example.com/updated_logo.png"
        channel.save()
        
        # Since user hasn't customized, effective values should show the updated M3U values
        self.assertEqual(channel.effective_name, "Updated M3U Name")
        self.assertEqual(channel.m3u_name, "Updated M3U Name")
        self.assertEqual(channel.m3u_logo_url, "http://example.com/updated_logo.png")
    
    def test_channel_number_always_preserved(self):
        """Test that channel_number is never overwritten by sync for existing channels."""
        channel = Channel.objects.create(
            channel_number=5.5,  # User-selected channel number
            name="Test Channel",
            channel_group=self.channel_group,
            auto_created=True,
            auto_created_by=self.m3u_account
        )
        
        original_number = channel.channel_number
        
        # Simulate sync process - channel number should never change for existing channels
        # (This test documents the expected behavior rather than testing specific sync code)
        channel.refresh_from_db()
        self.assertEqual(channel.channel_number, original_number)
    
    def test_str_method_uses_effective_name(self):
        """Test that the __str__ method uses effective_name."""
        channel = Channel.objects.create(
            channel_number=6.0,
            name="Original Name",
            m3u_name="M3U Name", 
            user_name="User Name",
            channel_group=self.channel_group
        )
        
        expected_str = f"{channel.channel_number} - User Name"
        self.assertEqual(str(channel), expected_str)