BC_SPEC_ALLOW = (
    0x01,  # Join Game - essential for world initialization
    0x02,  # Chat Message - spectators should see chat
    0x03,  # Time Update - keep day/night cycle synced
    0x04,  # Entity Equipment - maybe useful for seeing player gear?
    0x05,  # Spawn Position - world spawn point
    # 0x06,  # Update Health - player-specific, don't send
    0x07,  # Respawn - dimension changes
    0x08,  # Player Position And Look - camera position updates
    # 0x09,  # Held Item Change - player-specific inventory
    0x0A,  # Use Bed - show when player sleeps
    0x0B,  # Animation - player animations (arm swing, damage, etc.)
    0x0C,  # Spawn Player - show other players
    0x0D,  # Collect Item - item pickup animations
    0x0E,  # Spawn Object - entities like arrows, items
    0x0F,  # Spawn Mob - mobs in world
    0x10,  # Spawn Painting - world decorations
    0x11,  # Spawn Experience Orb - world objects
    0x12,  # Entity Velocity - entity movement (needed for player knockback)
    0x13,  # Destroy Entities - remove entities
    0x14,  # Entity - base entity packet
    0x15,  # Entity Relative Move - entity position updates
    0x16,  # Entity Look - entity rotation
    0x17,  # Entity Look And Relative Move - combined movement
    0x18,  # Entity Teleport - entity teleportation
    0x19,  # Entity Head Look - entity head rotation
    0x1A,  # Entity Status - entity state changes
    0x1B,  # Attach Entity - entity attachments (like riding)
    0x1C,  # Entity Metadata - entity data updates
    0x1D,  # Entity Effect - potion effects on entities
    0x1E,  # Remove Entity Effect - remove potion effects
    # 0x1F,  # Set Experience - player-specific
    0x20,  # Entity Properties - entity attributes
    0x21,  # Chunk Data - world chunks
    0x22,  # Multi Block Change - block updates
    0x23,  # Block Change - single block update
    0x24,  # Block Action - block animations (pistons, chests)
    0x25,  # Block Break Animation - block breaking progress
    0x26,  # Map Chunk Bulk - multiple chunks
    0x27,  # Explosion - explosions
    0x28,  # Effect - world effects (sounds, particles)
    0x29,  # Sound Effect - sound events
    0x2A,  # Particle - particle effects
    # 0x2B,  # Change Game State - some are player-specific (like gamemode)
    0x2C,  # Spawn Global Entity - lightning
    # 0x2D,  # Open Window - player-specific UI
    # 0x2E,  # Close Window - player-specific UI
    # 0x2F,  # Set Slot - player inventory
    # 0x30,  # Window Items - player inventory
    # 0x31,  # Window Property - player-specific (furnace progress, etc)
    # 0x32,  # Confirm Transaction - player-specific
    0x33,  # Update Sign - sign text updates
    0x34,  # Maps - map data
    0x35,  # Update Block Entity - tile entity data (signs, chests)
    # 0x36,  # Sign Editor Open - player-specific
    0x37,  # Statistics - could show for context
    0x38,  # Player List Item - tab list updates
    # 0x39,  # Player Abilities - spectators have their own ability flags
    # 0x3A,  # Tab Complete - player-specific
    0x3B,  # Scoreboard Objective - scoreboard display
    0x3C,  # Update Score - scoreboard updates
    0x3D,  # Display Scoreboard - scoreboard position
    0x3E,  # Teams - team information (critical for Bedwars)
    0x3F,  # Plugin Message - custom data (might be important)
    0x40,  # Disconnect - connection close
    0x41,  # Server Difficulty - sync difficulty display
    0x42,  # Combat Event - combat information
    0x43,  # Camera - camera entity
    0x44,  # World Border - world border updates
    # 0x45,  # Title - title/subtitle/actionbar text (we have custom handling for this in plugins/broadcaster.py)
    # 0x46,  # Set Compression - connection-specific
    0x47,  # Player List Header/Footer - tab list header
    0x48,  # Resource Pack Send - resource pack info
    0x49,  # Update Entity NBT - detailed entity data (item frames, armor stands, etc)
)
