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

using OpenRA.Graphics;
using OpenRA.Mods.Common.Traits;
using OpenRA.Mods.Common.Traits.Render;
using OpenRA.Mods.OpenE2140.Activites.Move;
using OpenRA.Mods.OpenE2140.Graphics;
using OpenRA.Mods.OpenE2140.Helpers.Reflection;
using OpenRA.Mods.OpenE2140.Traits.Production;
using static OpenRA.Mods.Common.Traits.Mobile;

namespace OpenRA.Mods.OpenE2140.Traits.Rendering.SpriteCutOff;

public class ProductionExitRenderSpritesInfo : RenderSpritesInfo
{
	public override object Create(ActorInitializer init)
	{
		return new ProductionExitRenderSprites(init, this);
	}
}

public class ProductionExitRenderSprites : RenderSprites
{
	private readonly RenderSpritesReflectionHelper reflectionHelper;

	public ProductionExitRenderSprites(ActorInitializer init, RenderSpritesInfo info)
		: base(init, info)
	{
		this.reflectionHelper = new RenderSpritesReflectionHelper(this);
	}

	public override IEnumerable<IRenderable> Render(Actor self, WorldRenderer worldRenderer)
	{
		if (self.CurrentActivity is not (LeaveProductionActivity or ProductionExitMove or ReturnToCellActivity))
			return base.Render(self, worldRenderer);

		return this.RenderCutOffSprites(self, worldRenderer);
	}

	private IEnumerable<IRenderable> RenderCutOffSprites(Actor self, WorldRenderer worldRenderer)
	{
		var producer = self.TraitOrDefault<ProducerMark>()?.Producer;
		if (producer == null)
			return Enumerable.Empty<IRenderable>();

		var cellTopEdgeWPos = producer.CenterPosition + (producer.Exits()?.FirstOrDefault()?.Info?.SpawnOffset ?? WVec.Zero);
		var cellTopEdge = worldRenderer.ScreenPxPosition(cellTopEdgeWPos);

		return this.reflectionHelper.RenderAnimations(
			self,
			worldRenderer,
			this.reflectionHelper.GetVisibleAnimations(),
			(anim, renderables) =>
			{
				SpriteCutOffHelper.ApplyCutOff(
					renderables,
					r =>
					{
						if (r is not SpriteRenderable spriteRenderable)
							return 0;

						var renderBounds = spriteRenderable.ScreenBounds(worldRenderer);

						var cutOffPos = worldRenderer.ProjectedPosition(cellTopEdge - renderBounds.Location);

						if (spriteRenderable.Offset != WVec.Zero)
							cutOffPos -= spriteRenderable.Pos - spriteRenderable.Offset - cellTopEdgeWPos;

						return cutOffPos.Y;
					},
					CutOffDirection.Top);
			}
		);
	}
}
