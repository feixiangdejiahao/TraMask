    it('Removed pair works when the query is created before the removal', () => {
        const Likes = relation();
        const apple = world.spawn();
        const banana = world.spawn();
        const player = world.spawn(Likes(apple), Likes(banana));
        const Removed = createRemoved();

        expect(world.query(Removed(Likes(apple)))).toHaveLength(0);

        player.remove(Likes(apple));

        expect(world.query(Removed(Likes(apple)))).toContain(player);
    });