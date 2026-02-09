/*
 * Custom admin command for headless terrain scanning.
 * Queries GeoEngine directly for height + NSWE data in batches.
 */
package org.l2jmobius.gameserver.handler.admincommandhandlers;

import java.util.Base64;

import org.l2jmobius.gameserver.geoengine.GeoEngine;
import org.l2jmobius.gameserver.handler.IAdminCommandHandler;
import org.l2jmobius.gameserver.model.World;
import org.l2jmobius.gameserver.model.actor.instance.PlayerInstance;
import org.l2jmobius.gameserver.network.clientpackets.Say2;
import org.l2jmobius.gameserver.network.serverpackets.CreatureSay;

/**
 * Terrain scan admin command for headless geodata extraction.
 *
 * Usage:
 *   //scan_geo <regionX> <regionY> <blockY>
 *     Scans one row of 256 blocks at the given blockY within the region.
 *     Returns base64-encoded height(short LE) + nswe(byte) for each block.
 *     Response format: GEODATA|regionX|regionY|blockY|<base64>
 *
 *   //scan_geo_check <regionX> <regionY>
 *     Checks if geodata is loaded for this region.
 *     Response: GEODATA_CHECK|regionX|regionY|loaded
 */
public class AdminTerrainScan implements IAdminCommandHandler
{
	private static final String[] ADMIN_COMMANDS =
	{
		"admin_scan_geo",
		"admin_scan_geo_check",
	};

	@Override
	public boolean useAdminCommand(String command, PlayerInstance activeChar)
	{
		final String[] parts = command.split(" ");

		try
		{
			if (parts[0].equals("admin_scan_geo"))
			{
				if (parts.length < 4)
				{
					sendResponse(activeChar, "Usage: //scan_geo <regionX> <regionY> <blockY>");
					return true;
				}

				final int regionX = Integer.parseInt(parts[1]);
				final int regionY = Integer.parseInt(parts[2]);
				final int blockY = Integer.parseInt(parts[3]);

				if (blockY < 0 || blockY >= 256)
				{
					sendResponse(activeChar, "blockY must be 0-255");
					return true;
				}

				scanBlockRow(activeChar, regionX, regionY, blockY);
			}
			else if (parts[0].equals("admin_scan_geo_check"))
			{
				if (parts.length < 3)
				{
					sendResponse(activeChar, "Usage: //scan_geo_check <regionX> <regionY>");
					return true;
				}

				final int regionX = Integer.parseInt(parts[1]);
				final int regionY = Integer.parseInt(parts[2]);

				checkRegion(activeChar, regionX, regionY);
			}
		}
		catch (NumberFormatException e)
		{
			sendResponse(activeChar, "Invalid number format: " + e.getMessage());
		}

		return true;
	}

	/**
	 * Scan one row of 256 blocks within a region.
	 * For each block, queries GeoEngine for height and NSWE at the block center.
	 * Sends result as base64-encoded binary data in a CreatureSay packet.
	 */
	private void scanBlockRow(PlayerInstance player, int regionX, int regionY, int blockY)
	{
		final GeoEngine geo = GeoEngine.getInstance();

		// 256 blocks * 3 bytes each (2 byte height LE + 1 byte NSWE)
		final byte[] data = new byte[256 * 3];

		// Region origin in world coordinates
		// regionX/Y are tile coordinates (e.g., 16-26 for X, 10-25 for Y)
		final int regionWorldX = (regionX - 20) * 32768;
		final int regionWorldY = (regionY - 18) * 32768;

		for (int bx = 0; bx < 256; bx++)
		{
			// Center of block (bx, blockY) within the region
			final int worldX = regionWorldX + (bx * 128) + 64;
			final int worldY = regionWorldY + (blockY * 128) + 64;

			final int geoX = GeoEngine.getGeoX(worldX);
			final int geoY = GeoEngine.getGeoY(worldY);

			short height;
			byte nswe;

			if (geo.hasGeoPos(geoX, geoY))
			{
				height = geo.getHeightNearest(geoX, geoY, 0);
				// Use the found height as reference Z for accurate NSWE
				nswe = geo.getNsweNearest(geoX, geoY, height);
			}
			else
			{
				height = 0;
				nswe = (byte) 0xFF; // All directions open (no geodata)
			}

			final int offset = bx * 3;
			data[offset] = (byte) (height & 0xFF);         // height low byte
			data[offset + 1] = (byte) ((height >> 8) & 0xFF); // height high byte
			data[offset + 2] = nswe;
		}

		final String b64 = Base64.getEncoder().encodeToString(data);
		final String msg = "GEODATA|" + regionX + "|" + regionY + "|" + blockY + "|" + b64;

		player.sendPacket(new CreatureSay(0, Say2.ALL, "SYS", msg));
	}

	/**
	 * Check if geodata is loaded for a region.
	 */
	private void checkRegion(PlayerInstance player, int regionX, int regionY)
	{
		final GeoEngine geo = GeoEngine.getInstance();

		// Check center of region
		final int worldX = ((regionX - 20) * 32768) + 16384;
		final int worldY = ((regionY - 18) * 32768) + 16384;
		final int geoX = GeoEngine.getGeoX(worldX);
		final int geoY = GeoEngine.getGeoY(worldY);

		final boolean loaded = geo.hasGeoPos(geoX, geoY);

		final String msg = "GEODATA_CHECK|" + regionX + "|" + regionY + "|" + (loaded ? "1" : "0");
		player.sendPacket(new CreatureSay(0, Say2.ALL, "SYS", msg));
	}

	private void sendResponse(PlayerInstance player, String message)
	{
		player.sendPacket(new CreatureSay(0, Say2.ALL, "SYS", message));
	}

	@Override
	public String[] getAdminCommandList()
	{
		return ADMIN_COMMANDS;
	}
}
