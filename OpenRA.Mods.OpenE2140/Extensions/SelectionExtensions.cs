﻿#region Copyright & License Information

/*
 * Copyright (c) The OpenE2140 Developers and Contributors
 * This file is part of OpenE2140, which is free software. It is made
 * available to you under the terms of the GNU General Public License
 * as published by the Free Software Foundation, either version 3 of
 * the License, or (at your option) any later version. For more
 * information, see COPYING.
 */

#endregion

using OpenRA.Traits;

namespace OpenRA.Mods.OpenE2140.Extensions;

public static class SelectionExtensions
{
	public static bool TryAdd(this ISelection selection, Actor actor)
	{
		if (selection.Contains(actor))
			return false;

		selection.Add(actor);
		return true;
	}
}
