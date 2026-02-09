/*
 * Admin command to export geodata from GeoEngine memory to L2D files.
 * Produces bit-perfect .l2d files preserving flat/complex/multilayer blocks.
 */
package org.l2jmobius.gameserver.handler.admincommandhandlers;

import java.io.File;

import org.l2jmobius.Config;
import org.l2jmobius.gameserver.geoengine.GeoEngine;
import org.l2jmobius.gameserver.handler.IAdminCommandHandler;
import org.l2jmobius.gameserver.model.World;
import org.l2jmobius.gameserver.model.actor.instance.PlayerInstance;
import org.l2jmobius.gameserver.network.clientpackets.Say2;
import org.l2jmobius.gameserver.network.serverpackets.CreatureSay;

/**
 * Export geodata directly from GeoEngine memory to L2D files.
 *
 * Usage:
 *   //geo_export <regionX> <regionY>
 *     Exports one region to geodata_export/ directory.
 *
 *   //geo_export_all
 *     Exports all loaded regions to geodata_export/ directory.
 *
 *   //geo_export_all <outputDir>
 *     Exports all to a custom directory.
 */
public class AdminGeoExport implements IAdminCommandHandler
{
	private static final String[] ADMIN_COMMANDS =
	{
		"admin_geo_export",
		"admin_geo_export_all",
	};

	@Override
	public boolean useAdminCommand(String command, PlayerInstance activeChar)
	{
		final String[] parts = command.split(" ");

		try
		{
			if (parts[0].equals("admin_geo_export"))
			{
				if (parts.length < 3)
				{
					sendMsg(activeChar, "Usage: //geo_export <regionX> <regionY>");
					return true;
				}

				final int regionX = Integer.parseInt(parts[1]);
				final int regionY = Integer.parseInt(parts[2]);

				final String outputDir = parts.length > 3 ? parts[3] : getDefaultOutputDir();

				exportRegion(activeChar, regionX, regionY, outputDir);
			}
			else if (parts[0].equals("admin_geo_export_all"))
			{
				final String outputDir = parts.length > 1 ? parts[1] : getDefaultOutputDir();

				exportAll(activeChar, outputDir);
			}
		}
		catch (NumberFormatException e)
		{
			sendMsg(activeChar, "Invalid number: " + e.getMessage());
		}

		return true;
	}

	private String getDefaultOutputDir()
	{
		// Export next to the geodata folder, in geodata_export/
		return Config.GEODATA_PATH + "../geodata_export/";
	}

	private void exportRegion(PlayerInstance player, int regionX, int regionY, String outputDir)
	{
		// Validate region bounds
		if (regionX < World.TILE_X_MIN || regionX > World.TILE_X_MAX
			|| regionY < World.TILE_Y_MIN || regionY > World.TILE_Y_MAX)
		{
			sendMsg(player, "Invalid region: " + regionX + "_" + regionY
				+ " (valid: " + World.TILE_X_MIN + "-" + World.TILE_X_MAX
				+ " x " + World.TILE_Y_MIN + "-" + World.TILE_Y_MAX + ")");
			return;
		}

		// Check if geodata is loaded for this region
		final int centerWorldX = ((regionX - 20) * 32768) + 16384;
		final int centerWorldY = ((regionY - 18) * 32768) + 16384;
		final int geoX = GeoEngine.getGeoX(centerWorldX);
		final int geoY = GeoEngine.getGeoY(centerWorldY);

		if (!GeoEngine.getInstance().hasGeoPos(geoX, geoY))
		{
			sendMsg(player, "GEO_EXPORT|" + regionX + "|" + regionY + "|SKIP|no geodata loaded");
			return;
		}

		// Create output directory
		final File dir = new File(outputDir);
		if (!dir.exists())
		{
			dir.mkdirs();
		}

		final String filename = regionX + "_" + regionY + ".l2d";
		final String fullPath = outputDir + filename;

		final long start = System.currentTimeMillis();
		final boolean ok = GeoEngine.getInstance().exportRegion(regionX, regionY, fullPath);
		final long elapsed = System.currentTimeMillis() - start;

		if (ok)
		{
			final File f = new File(fullPath);
			sendMsg(player, "GEO_EXPORT|" + regionX + "|" + regionY + "|OK|"
				+ f.length() + "|" + elapsed + "ms");
		}
		else
		{
			sendMsg(player, "GEO_EXPORT|" + regionX + "|" + regionY + "|FAIL|export error");
		}
	}

	private void exportAll(PlayerInstance player, String outputDir)
	{
		final long startAll = System.currentTimeMillis();
		int exported = 0;
		int skipped = 0;
		long totalSize = 0;

		sendMsg(player, "GEO_EXPORT_ALL|START|" + outputDir);

		for (int rx = World.TILE_X_MIN; rx <= World.TILE_X_MAX; rx++)
		{
			for (int ry = World.TILE_Y_MIN; ry <= World.TILE_Y_MAX; ry++)
			{
				// Check if geodata is loaded
				final int centerWorldX = ((rx - 20) * 32768) + 16384;
				final int centerWorldY = ((ry - 18) * 32768) + 16384;
				final int geoX = GeoEngine.getGeoX(centerWorldX);
				final int geoY = GeoEngine.getGeoY(centerWorldY);

				if (!GeoEngine.getInstance().hasGeoPos(geoX, geoY))
				{
					skipped++;
					continue;
				}

				// Create output directory
				final File dir = new File(outputDir);
				if (!dir.exists())
				{
					dir.mkdirs();
				}

				final String filename = rx + "_" + ry + ".l2d";
				final String fullPath = outputDir + filename;

				if (GeoEngine.getInstance().exportRegion(rx, ry, fullPath))
				{
					exported++;
					totalSize += new File(fullPath).length();

					// Progress update every 10 regions
					if (exported % 10 == 0)
					{
						sendMsg(player, "GEO_EXPORT_ALL|PROGRESS|" + exported + "|" + rx + "_" + ry);
					}
				}
			}
		}

		final long elapsedAll = System.currentTimeMillis() - startAll;
		sendMsg(player, "GEO_EXPORT_ALL|DONE|" + exported + "|" + skipped
			+ "|" + (totalSize / 1024) + "KB|" + elapsedAll + "ms");
	}

	private void sendMsg(PlayerInstance player, String message)
	{
		player.sendPacket(new CreatureSay(0, Say2.ALL, "SYS", message));
	}

	@Override
	public String[] getAdminCommandList()
	{
		return ADMIN_COMMANDS;
	}
}
